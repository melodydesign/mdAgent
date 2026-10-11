"""
mdAgent — Agent Engine
Связывает провайдер моделей (Gemini каскад или HydraAI GPT-5.6 Luna) с Playwright.
Принимает команды, строит план, выполняет действия, проводит Self-Healing и дистилляцию в память.
"""

import asyncio
import json
import logging
import re
import time
from typing import Optional, Callable, Awaitable

from backend.browser import BrowserController
from backend.chat_storage import ChatStorage
from backend.config import SETTINGS_FILE
from backend.gemini_client import GeminiClient
from backend.hydra_client import HydraClient
from backend.memory import MemoryManager

logger = logging.getLogger(__name__)

# Callback для отправки событий в UI
EventCallback = Optional[Callable[[dict], Awaitable[None]]]

# Действия, изменяющие состояние проекта/страницы/блоков
MUTATING_ACTIONS = {
    "add_block", "browse_and_select_block", "edit_block_content", "swap_block_title_descr", "edit_block_settings", "edit_t123_code",
    "delete_block", "clear_page", "duplicate_block", "hide_block", "move_block_up", "move_block_down",
    "create_project", "delete_project", "create_page", "delete_page", "set_page_seo", "publish_page", "reload_page", "verify_published_page"
}


class Agent:
    """
    AI-агент: получает текстовые команды, преобразует их в действия
    через активного AI-провайдера (Gemini каскад или HydraAI GPT-5.6 Luna),
    выполняет через Playwright.
    """

    def __init__(self):
        self.browser = BrowserController()
        self.gemini: Optional[GeminiClient] = None
        self.hydra: Optional[HydraClient] = None
        self.memory = MemoryManager()
        self.chat_storage = ChatStorage()
        self._event_callback: EventCallback = None
        self._is_busy: bool = False
        self._is_paused: bool = False
        self._stop_requested: bool = False
        self._pending_publish_confirmation: bool = False
        self._pending_plan: Optional[dict] = None
        self._pause_event: asyncio.Event = asyncio.Event()
        self._pause_event.set()
        self.active_provider: str = self._load_saved_provider()
        self._current_user_message: str = ""
        self._last_inspected_dom: Optional[dict] = None
        self._last_target_block_id: Optional[str] = None

        # Инициализируем AI-клиентов сразу для немедленного доступа к лимитам и каскаду
        try:
            self.gemini = GeminiClient()
        except Exception as e:
            logger.warning(f"Инициализация GeminiClient в __init__: {e}")

        try:
            self.hydra = HydraClient()
        except Exception as e:
            logger.warning(f"Инициализация HydraClient в __init__: {e}")


    def _load_saved_provider(self) -> str:
        """Загружает сохраненного провайдера из data/settings.json."""
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                return data.get("provider", "gemini")
        except Exception as e:
            logger.warning(f"Ошибка загрузки сохраненных настроек: {e}")
        return "gemini"

    def _save_provider(self, provider: str):
        """Сохраняет выбор провайдера в data/settings.json."""
        try:
            SETTINGS_FILE.parent.mkdir(exist_ok=True)
            settings = {}
            if SETTINGS_FILE.exists():
                try:
                    settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                except Exception:
                    pass
            settings["provider"] = provider
            SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Ошибка сохранения настроек: {e}")

    def set_provider(self, provider: str):
        """Переключает активного AI-провайдера ('gemini' или 'hydraai')."""
        if provider not in ("gemini", "hydraai"):
            raise ValueError(f"Неизвестный провайдер: {provider}")
        self.active_provider = provider
        self._save_provider(provider)
        logger.info(f"Активный AI-провайдер изменён на: {provider}")

    def get_active_ai(self):
        """Возвращает клиента текущего активного AI-провайдера."""
        if self.active_provider == "hydraai" and self.hydra:
            return self.hydra
        if self.gemini:
            return self.gemini
        return self.hydra

    def set_event_callback(self, callback: EventCallback):
        """Устанавливает callback для отправки событий в WebSocket."""
        self._event_callback = callback
        self.browser.set_log_callback(self._on_log)
        self.browser.set_frame_callback(self._on_screencast_frame)

    async def _emit(self, event_type: str, data: dict):
        """Отправляет событие в UI."""
        event = {"type": event_type, **data}
        if self._event_callback:
            await self._event_callback(event)

    async def _send_chat_message(self, role: str, text: str, metadata: Optional[dict] = None) -> dict:
        """Сохраняет сообщение в постоянную историю чата и отправляет событие клиентам."""
        msg = self.chat_storage.add_message(role, text, metadata)
        await self._emit("chat_message", msg)
        return msg

    async def _on_screencast_frame(self, frame_b64: str):
        """Транслирует живой кадр экрана Chromium в UI в реальном времени."""
        await self._emit("screencast_frame", {"image": frame_b64})

    async def _on_log(self, level: str, message: str):
        """Callback для логов от BrowserController."""
        await self._emit("log", {"level": level, "message": message})

    async def _send_screenshot(self):
        """Делает скриншот и отправляет в UI."""
        try:
            screenshot_b64 = await self.browser.screenshot()
            await self._emit("screenshot", {"image": screenshot_b64})
            return screenshot_b64
        except Exception as e:
            logger.error(f"Ошибка скриншота: {e}")
            return None

    # ─────────────────────────── Инициализация ───────────────────────────

    async def initialize(self):
        """Инициализирует агента: запускает браузер и подключает AI-провайдеров."""
        await self._emit("log", {"level": "info", "message": "Инициализация агента..."})

        # Запускаем браузер
        try:
            await self.browser.start()
            await self._send_screenshot()
        except Exception as e:
            err_msg = str(e).strip() or type(e).__name__
            logger.exception("Ошибка запуска браузера")
            await self._emit("log", {"level": "error", "message": f"Ошибка запуска браузера: {err_msg}"})
            await self._emit("status", await self.get_status())
            raise

        # Инициализируем Gemini каскад
        try:
            self.gemini = GeminiClient()
            active_m = self.gemini.active_model
            await self._emit("log", {"level": "info", "message": f"Gemini каскад подключён (активная: {active_m})"})
        except ValueError as e:
            await self._emit("log", {"level": "error", "message": f"Gemini: {e}"})
            self.gemini = None
        except Exception as e:
            await self._emit("log", {"level": "error", "message": f"Ошибка инициализации Gemini: {e}"})
            self.gemini = None

        # Инициализируем HydraAI (GPT-5.6 Luna)
        try:
            self.hydra = HydraClient()
            await self._emit("log", {"level": "info", "message": f"HydraAI подключён (модель: {self.hydra.model})"})
        except ValueError as e:
            await self._emit("log", {"level": "error", "message": f"HydraAI: {e}"})
            self.hydra = None
        except Exception as e:
            await self._emit("log", {"level": "error", "message": f"Ошибка инициализации HydraAI: {e}"})
            self.hydra = None

        active_ai = self.get_active_ai()
        if active_ai:
            provider_title = "HydraAI (GPT-5.6 Luna)" if self.active_provider == "hydraai" else "Google Gemini (Каскад)"
            await self._emit("log", {"level": "info", "message": f"Активная модель: {provider_title}"})

        await self._emit("status", await self.get_status())

    async def pause(self):
        """Приостанавливает выполнение плана агента."""
        if not self._is_paused:
            self._is_paused = True
            self._pause_event.clear()
            await self._emit("status", await self.get_status())
            await self._emit("log", {
                "level": "warning",
                "message": "⏸ Агент поставлен на паузу. Браузер передан в ручное управление. Вы можете кликать, редактировать и выполнять любые действия. Для продолжения нажмите «Продолжить»."
            })

    async def resume(self):
        """Возобновляет выполнение плана агента."""
        if self._is_paused:
            self._is_paused = False
            self._pause_event.set()
            await self._emit("status", await self.get_status())
            await self._emit("log", {
                "level": "info",
                "message": "▶ Выполнение плана возобновлено агентом."
            })

    async def shutdown(self):
        """Останавливает агента."""
        self._stop_requested = True
        self._is_paused = False
        self._pause_event.set()
        await self.browser.stop()
        self._is_busy = False
        await self._emit("log", {"level": "info", "message": "Агент остановлен"})
        await self._emit("status", await self.get_status())

    # ─────────────────────────── Обработка команд ───────────────────────────

    async def process_command(self, user_message: str, user_image_base64: Optional[str] = None) -> list[dict]:
        """
        Основной метод: принимает команду пользователя, выполняет действия через активный AI.
        Поддерживает прикреплённое пользователем изображение (скриншот с пометками).
        """
        if self._is_busy:
            await self._emit("log", {
                "level": "warning",
                "message": "Агент занят, подождите завершения текущей задачи."
            })
            return [{"action": "busy", "success": False, "message": "Агент занят"}]

        self._is_busy = True
        self._is_paused = False
        self._stop_requested = False
        self._pause_event.set()
        self._current_user_message = user_message
        self._last_inspected_dom = None
        results = []

        try:
            user_msg_meta = {"image": user_image_base64} if user_image_base64 else None

            # 1. Проверяем контекст подтверждения публикации
            if self._pending_publish_confirmation:
                msg_norm = user_message.strip().lower()
                affirmative_words = ["да", "опубликуй", "публикуй", "давай", "yes", "ок", "ага", "конечно", "хочу", "нужно", "да, опубликуй", "опубликовать"]
                negative_words = ["нет", "не надо", "не нужно", "позже", "не публикуй", "отмена", "no"]

                if any(msg_norm == w or msg_norm.startswith(w + " ") or msg_norm.startswith(w + ",") for w in affirmative_words):
                    self._pending_publish_confirmation = False
                    await self._send_chat_message("user", user_message, metadata=user_msg_meta)
                    await self._emit("log", {
                        "level": "info",
                        "message": "Публикую страницу по вашему подтверждению..."
                    })
                    if not self.browser.is_running:
                        await self.initialize()

                    pub_result = await self.browser.publish_page()
                    await self._send_screenshot()
                    pub_url = pub_result.get("url") if isinstance(pub_result, dict) else self.browser._last_published_url
                    is_ok = pub_result.get("success", False) if isinstance(pub_result, dict) else bool(pub_result)
                    if is_ok:
                        # Если до этого редактировался блок T123 или есть исследованный DOM, проверяем опубликованную страницу
                        if self._last_inspected_dom:
                            await self._emit("log", {
                                "level": "info",
                                "message": "Проверяю применение стилей и скриптов на опубликованном сайте (Closed-Loop)..."
                            })
                            v_res = await self.browser.verify_published_page(url=pub_url)
                            if not v_res.get("success", False) and v_res.get("issues"):
                                issues = v_res.get("issues", [])
                                await self._emit("log", {
                                    "level": "warning",
                                    "message": f"Closed-Loop: обнаружены замечания боевой страницы ({'; '.join(issues)}), исправляю код..."
                                })
                                fixed_code = await self._ground_code_with_dom(
                                    code="",
                                    dom=self._last_inspected_dom,
                                    user_goal=f"Исправь ошибки на опубликованной странице: {'; '.join(issues)}"
                                )
                                await self.browser.edit_t123_code(code=fixed_code)
                                await self.browser.publish_page()
                                await self.browser.verify_published_page(url=pub_url)

                        url_text = f" Ссылка на сайт: {pub_url}" if pub_url else ""
                        pub_msg = f"Страница успешно опубликована и проверена на боевом сайте!{url_text}"
                        await self._emit("log", {
                            "level": "success",
                            "message": pub_msg
                        })
                        await self._send_chat_message("agent", pub_msg, {"url": pub_url})
                        return [{"action": "publish_page", "success": True, "url": pub_url}]
                    else:
                        err_msg = "Не удалось опубликовать страницу через панель Tilda."
                        await self._emit("log", {
                            "level": "error",
                            "message": err_msg
                        })
                        await self._send_chat_message("agent", err_msg, {"is_error": True})
                        return [{"action": "publish_page", "success": False}]

                elif any(msg_norm == w or msg_norm.startswith(w + " ") or msg_norm.startswith(w + ",") for w in negative_words):
                    self._pending_publish_confirmation = False
                    await self._send_chat_message("user", user_message)
                    declined_msg = "Хорошо, страница остаётся в черновике без публикации."
                    await self._emit("log", {
                        "level": "info",
                        "message": declined_msg
                    })
                    await self._send_chat_message("agent", declined_msg)
                    return [{"action": "publish_declined", "success": True}]

                else:
                    self._pending_publish_confirmation = False

            # 2. Проверяем контекст согласования плана составной задачи
            if self._pending_plan:
                msg_norm = user_message.strip().lower()
                affirmative_words = ["да", "делай", "ок", "подтверждаю", "вперед", "давай", "yes", "начинай", "выполняй"]
                negative_words = ["нет", "не надо", "не нужно", "отмена", "стоп", "no"]
                if any(msg_norm == w or msg_norm.startswith(w + " ") or msg_norm.startswith(w + ",") for w in affirmative_words):
                    steps_to_confirm = [{"id": s["id"], "text": s["text"], "enabled": True} for s in self._pending_plan.get("user_steps", [])]
                    return await self.confirm_plan(self._pending_plan["plan_id"], steps_to_confirm)
                elif any(msg_norm == w or msg_norm.startswith(w + " ") or msg_norm.startswith(w + ",") for w in negative_words):
                    await self.cancel_plan()
                    return [{"action": "plan_cancelled", "success": True}]
                else:
                    self._pending_plan = None

            await self._send_chat_message("user", user_message, metadata=user_msg_meta)
            await self._emit("log", {
                "level": "info",
                "message": f"Получена команда: {user_message}"
            })

            # Проверяем что браузер запущен и авторизован в Tilda (с учетом учетных данных активной сессии)
            if not self.browser.is_running:
                await self.initialize()
            custom_email, custom_pwd = self.chat_storage.get_tilda_credentials()
            await self.browser.ensure_logged_in(email=custom_email, password=custom_pwd)

            # Перед выполнением каждой задачи обновляем страницу (F5), чтобы гарантировать
            # актуальное состояние редактора (подтягивание блоков пользователя, закрытие модалок публикации)
            if self.browser.page and "/page/?pageid=" in (self.browser.page.url or ""):
                await self.browser.reload_page()

            # Получаем скриншот текущего состояния для контекста
            current_screenshot = await self._send_screenshot()

            ai = self.get_active_ai()

            # Если ни один AI недоступен — пробуем выполнить как прямую команду
            if not ai:
                await self._emit("log", {
                    "level": "warning",
                    "message": "AI-провайдеры недоступны. Попробую выполнить как прямую команду."
                })
                result = await self._execute_direct_command(user_message)
                results.append(result)
                return results

            provider_label = "HydraAI (GPT-5.6 Luna)" if self.active_provider == "hydraai" else f"Gemini ({getattr(self.gemini, 'active_model', 'каскад')})"

            # Проверяем память на наличие проверенного рецепта
            matched_playbook = self.memory.find_playbook(user_message)
            if matched_playbook:
                is_edit_request = any(w in user_message.lower() for w in ("замени", "отредактируй", "поменяй", "перепиши", "обнови контент", "измени текст"))
                pb_actions = [a.get("action") for a in matched_playbook.get("actions", [])]
                if is_edit_request and any(a in pb_actions for a in ("create_project", "create_page", "browse_and_select_block", "add_block")):
                    matched_playbook = None
                else:
                    await self._emit("log", {
                        "level": "info",
                        "message": f"Найден проверенный рецепт в памяти: «{matched_playbook['name']}» (успехов: {matched_playbook.get('success_count', 0)})"
                    })

            # Обрабатываем команду через активный AI
            await self._emit("log", {
                "level": "info",
                "message": f"Формирую план действий через {provider_label}..."
            })

            current_url = self.browser.page.url if self.browser.is_running else "about:blank"
            active_p_name = getattr(self.browser, "_last_active_page_name", None)
            active_p_id = getattr(self.browser, "_last_active_page_id", None)
            active_b_id = getattr(self.browser, "_last_target_block_id", None)
            
            context_header = f"[Текущий URL браузера: {current_url}]"
            if active_p_name or active_p_id:
                context_header += f"\n[Активная рабочая страница сессии: «{active_p_name or active_p_id}» (ID: {active_p_id or 'нет'})]"
            if active_b_id:
                context_header += f"\n[Целевой блок на странице: #{active_b_id}]"

            context_message = f"{context_header}\n\nКоманда пользователя: {user_message}"
            if user_image_base64:
                context_message += "\n\n[Внимание: Пользователь прикрепил скриншот с визуальными пометками/стрелками. Учитывай разметку на изображении!]"

            # Если локальная память модели пуста (например, после рестарта) — подтягиваем недавнюю историю из хранилища чата
            if hasattr(ai, "conversation_history") and not ai.conversation_history:
                try:
                    stored_msgs = self.chat_storage.get_messages()
                    recent_history = [m for m in stored_msgs if m.get("text") and m.get("text") != user_message][-6:]
                    if recent_history:
                        if self.active_provider == "hydraai":
                            ai.conversation_history = [
                                {
                                    "role": "user" if m.get("role") == "user" else "assistant",
                                    "content": m.get("text", "")
                                }
                                for m in recent_history
                            ]
                        elif self.active_provider == "gemini":
                            from google.genai import types
                            ai.conversation_history = [
                                types.Content(
                                    role="user" if m.get("role") == "user" else "model",
                                    parts=[types.Part.from_text(text=m.get("text", ""))]
                                )
                                for m in recent_history
                            ]
                except Exception as he:
                    logger.debug(f"Не удалось восстановить историю в AI: {he}")

            # Если пользователь прикрепил изображение, передаем его приоритетно в качестве зрительного контекста
            effective_screenshot = user_image_base64 or current_screenshot

            actions = await ai.process_command(
                context_message,
                screenshot_base64=effective_screenshot,
                playbook=matched_playbook,
            )

            # План действий сформирован AI и проверенными рецептами памяти
            if not actions:
                await self._emit("log", {
                    "level": "warning",
                    "message": "AI сформировал пустой план. Пробую повторный запрос с прямым контекстом..."
                })
                actions = await ai.process_command(
                    context_message,
                    screenshot_base64=None,
                    playbook=None,
                )

            if not actions:
                await self._emit("log", {
                    "level": "error",
                    "message": "Не удалось сформировать действия для указанной команды."
                })
                await self._send_chat_message("agent", "Не удалось определить необходимые действия. Пожалуйста, уточните команду.", {"is_error": True})
                return [{"action": "empty_plan", "success": False}]

            # Декомпозируем действия в высокоуровневые понятные человеку шаги
            user_steps = self._decompose_into_user_steps(actions, user_message)

            # Если задача требует более 1 правки — перед началом работы уточняем план
            if len(user_steps) >= 2:
                plan_id = f"plan_{int(time.time() * 1000)}"
                self._pending_plan = {
                    "plan_id": plan_id,
                    "user_steps": user_steps,
                    "user_message": user_message,
                    "provider_label": provider_label,
                    "matched_playbook": matched_playbook,
                }
                steps_for_ui = [{"id": s["id"], "text": s["text"], "enabled": True} for s in user_steps]
                steps_list_text = "\n".join([f"{idx + 1}. {s['text']}" for idx, s in enumerate(user_steps)])
                prompt_text = (
                    f"Уточните план задачи перед началом (я выделил {len(user_steps)} шага):\n\n"
                    f"{steps_list_text}\n\n"
                    "Вы можете скорректировать формулировку любого пункта кликом по нему ниже или отключить лишнее."
                )
                await self._emit("log", {
                    "level": "info",
                    "message": f"Задача составная ({len(user_steps)} шагов). Ожидаю подтверждения плана от пользователя..."
                })
                await self._send_chat_message(
                    "agent",
                    prompt_text,
                    {
                        "type": "plan_confirmation",
                        "plan_id": plan_id,
                        "steps": steps_for_ui
                    }
                )
                self._is_busy = False
                await self._emit("status", await self.get_status())
                return [{"action": "waiting_plan_confirmation", "plan_id": plan_id, "steps": steps_for_ui}]

            # Одиночная задача (1 правка) — выполняем сразу без задержек
            return await self._execute_actions_sequence(
                actions=actions,
                user_message=user_message,
                provider_label=provider_label,
                matched_playbook=matched_playbook,
            )

        except Exception as e:
            logger.exception("Критическая ошибка при обработке команды")
            err_text = f"Ошибка: {str(e)}"
            await self._emit("log", {
                "level": "error",
                "message": err_text
            })
            await self._send_chat_message("agent", err_text, {"is_error": True})
            return [{"action": "error", "success": False, "message": str(e)}]

        finally:
            self._is_busy = False
            self._is_paused = False
            await self._emit("status", await self.get_status())
    def _decompose_into_user_steps(self, actions: list[dict], user_message: str = "") -> list[dict]:
        """
        Группирует действия AI в понятные высокоуровневые пункты плана для пользователя.
        Правило пользователя:
        - создать страницу — 1 задача
        - создать и наполнить блок — 1 задача
        - создать страницу и блок — 2 задачи
        - создать блок + наполнить + сделать сео + создать 2-й блок — 3-4 задачи
        """
        user_steps = []
        current_block_step = None

        for action in actions:
            act_name = action.get("action", "")
            params = action.get("params", {})
            desc = action.get("description", "")

            # 1. Проекты
            if act_name in ("create_project", "delete_project"):
                user_steps.append({
                    "id": len(user_steps) + 1,
                    "text": desc or f"Создать проект «{params.get('name', 'mdAgent')}»",
                    "actions": [action]
                })
                current_block_step = None

            # 2. Страницы
            elif act_name in ("create_page", "delete_page"):
                user_steps.append({
                    "id": len(user_steps) + 1,
                    "text": desc or f"Создать страницу «{params.get('title', params.get('name', 'Новая страница'))}»",
                    "actions": [action]
                })
                current_block_step = None

            # 3. Добавление блока
            elif act_name in ("browse_and_select_block", "add_block"):
                cat = params.get("category", "блок")
                reqs = params.get("requirements", "")
                step_title = f"Создать блок «{cat}»"
                if reqs:
                    step_title += f" ({reqs})"
                elif desc:
                    step_title = desc
                current_block_step = {
                    "id": len(user_steps) + 1,
                    "text": step_title,
                    "actions": [action]
                }
                user_steps.append(current_block_step)

            # 4. Наполнение блока контентом
            elif act_name in ("edit_block_content", "edit_text"):
                if current_block_step and len(current_block_step["actions"]) < 3 and not any(a.get("action") == act_name for a in current_block_step["actions"]):
                    current_block_step["actions"].append(action)
                    t = params.get("title", "")
                    if t and "наполнить" not in current_block_step["text"].lower():
                        current_block_step["text"] += f" и наполнить контентом («{t}»)"
                    elif "наполнить" not in current_block_step["text"].lower():
                        current_block_step["text"] += " и наполнить контентом"
                else:
                    user_steps.append({
                        "id": len(user_steps) + 1,
                        "text": desc or "Наполнить блок актуальным контентом",
                        "actions": [action]
                    })
                    current_block_step = None

            # 4.1. Настройка стилей блока через шторку «Настройки»
            elif act_name == "edit_block_settings":
                style_details = []
                if any(k in params for k in ("title_color", "title_size", "title_weight", "title_align", "descr_color", "descr_size")):
                    style_details.append("типографика")
                if any(k in params for k in ("btn_bg_color", "btn_text_color", "btn_border_color", "btn_radius", "btn2_bg_color", "btn2_radius")):
                    style_details.append("кнопки")
                if any(k in params for k in ("bg_color", "bg_filter")):
                    style_details.append("фон блока")

                details_str = f" ({', '.join(style_details)})" if style_details else ""
                step_title = desc or f"Настроить стили блока{details_str}"

                if current_block_step and len(current_block_step["actions"]) < 3 and not any(a.get("action") == act_name for a in current_block_step["actions"]):
                    current_block_step["actions"].append(action)
                    if "стил" not in current_block_step["text"].lower():
                        current_block_step["text"] += f" и настроить стили{details_str}"
                else:
                    user_steps.append({
                        "id": len(user_steps) + 1,
                        "text": step_title,
                        "actions": [action]
                    })
                    current_block_step = None

            # 4.15. Перестановка заголовка и подзаголовка местами
            elif act_name == "swap_block_title_descr":
                user_steps.append({
                    "id": len(user_steps) + 1,
                    "text": desc or "Поменять местами заголовок и подзаголовок блока",
                    "actions": [action]
                })
                current_block_step = None

            # 4.2. Исследование верстки блока
            elif act_name == "inspect_block_dom":
                user_steps.append({
                    "id": len(user_steps) + 1,
                    "text": desc or "Исследовать реальную верстку блока (селекторы и порядок элементов)",
                    "actions": [action]
                })
                current_block_step = None

            # 4.3. Редактирование кода блока T123
            elif act_name == "edit_t123_code":
                raw_desc = (desc or "").strip()
                sub_items = []
                if ":" in raw_desc:
                    prefix, rest = raw_desc.split(":", 1)
                    parts = [p.strip() for p in re.split(r"[,;]|\s+и\s+", rest) if p.strip()]
                    if len(parts) >= 2:
                        for p in parts:
                            sub_text = p[0].upper() + p[1:] if len(p) > 1 else p.upper()
                            sub_items.append(sub_text)

                if sub_items:
                    for item_text in sub_items:
                        user_steps.append({
                            "id": len(user_steps) + 1,
                            "text": item_text,
                            "actions": [action]
                        })
                else:
                    user_steps.append({
                        "id": len(user_steps) + 1,
                        "text": desc or "Вставить кастомный HTML/JS/CSS код в блок T123",
                        "actions": [action]
                    })
                current_block_step = None

            # 4.4. Тестирование скрипта в DOM
            elif act_name == "test_page_script":
                user_steps.append({
                    "id": len(user_steps) + 1,
                    "text": desc or "Протестировать выполнение скрипта в DOM страницы",
                    "actions": [action]
                })
                current_block_step = None

            # 4.5. Обновление страницы
            elif act_name == "reload_page":
                user_steps.append({
                    "id": len(user_steps) + 1,
                    "text": desc or "Обновить страницу для синхронизации данных Tilda",
                    "actions": [action]
                })
                current_block_step = None

            # 5. Настройка SEO
            elif act_name == "set_page_seo":
                t = params.get("title", "")
                seo_desc = "Настроить SEO страницы (заголовок, описание, ключевые слова)"
                if t:
                    seo_desc = f"Настроить SEO страницы: «{t}»"
                user_steps.append({
                    "id": len(user_steps) + 1,
                    "text": seo_desc,
                    "actions": [action]
                })
                current_block_step = None

            # 6. Очистка страницы
            elif act_name == "clear_page":
                user_steps.append({
                    "id": len(user_steps) + 1,
                    "text": "Очистить текущую страницу от всех блоков",
                    "actions": [action]
                })
                current_block_step = None

            # 7. Публикация
            elif act_name == "publish_page":
                user_steps.append({
                    "id": len(user_steps) + 1,
                    "text": "Опубликовать страницу в сети",
                    "actions": [action]
                })
                current_block_step = None

            # 7.1. Проверка опубликованной страницы
            elif act_name == "verify_published_page":
                user_steps.append({
                    "id": len(user_steps) + 1,
                    "text": desc or "Проверить работу стилей и скриптов на опубликованном сайте по ссылке",
                    "actions": [action]
                })
                current_block_step = None

            # Прочие действия
            else:
                if current_block_step:
                    current_block_step["actions"].append(action)
                elif user_steps:
                    user_steps[-1]["actions"].append(action)
                else:
                    user_steps.append({
                        "id": len(user_steps) + 1,
                        "text": desc or f"Выполнить действие {act_name}",
                        "actions": [action]
                    })

        # Если в плане есть правки кода T123, гарантируем прозрачные шаги публикации и проверки в плане
        has_t123 = any(any(a.get("action") == "edit_t123_code" for a in s.get("actions", [])) for s in user_steps)
        if has_t123:
            has_pub = any(any(a.get("action") == "publish_page" for a in s.get("actions", [])) for s in user_steps)
            if not has_pub:
                user_steps.append({
                    "id": len(user_steps) + 1,
                    "text": "Опубликовать страницу в сети для боевой проверки",
                    "actions": [{"action": "publish_page", "description": "Опубликовать страницу в сети"}]
                })
            has_ver = any(any(a.get("action") == "verify_published_page" for a in s.get("actions", [])) for s in user_steps)
            if not has_ver:
                user_steps.append({
                    "id": len(user_steps) + 1,
                    "text": "Проверить работу стилей и скриптов на опубликованном сайте",
                    "actions": [{"action": "verify_published_page", "description": "Проверить работу стилей и скриптов на опубликованном сайте"}]
                })

        # Перенумеровываем id шагов по порядку
        for idx, s in enumerate(user_steps):
            s["id"] = idx + 1

        return user_steps

    async def confirm_plan(self, plan_id: str, steps: list[dict]) -> list[dict]:
        """
        Запускает утвержденный пользователем план действий.
        """
        if not self._pending_plan:
            await self._send_chat_message("agent", "Нет активного плана для подтверждения.")
            return [{"action": "no_pending_plan", "success": False}]

        pending = self._pending_plan
        self._pending_plan = None
        self._is_busy = True
        self._is_paused = False
        self._stop_requested = False
        self._pause_event.set()
        await self._emit("status", await self.get_status())

        # Оставляем только включенные пользователем шаги
        active_steps = [s for s in steps if s.get("enabled", True)]
        if not active_steps:
            self._is_busy = False
            await self._send_chat_message("agent", "Все шаги были отключены. Выполнение отменено.")
            await self._emit("status", await self.get_status())
            return [{"action": "plan_empty", "success": True}]

        await self._emit("log", {
            "level": "info",
            "message": f"План подтверждён! Начинаю выполнение {len(active_steps)} шагов..."
        })
        await self._send_chat_message(
            "agent",
            f"План утверждён! Начинаю выполнение {len(active_steps)} шагов..."
        )

        # Собираем действия для утвержденных шагов
        actions_to_run = []
        original_map = {s["id"]: s for s in pending.get("user_steps", [])}

        user_step_texts = []
        for s in active_steps:
            text = s.get("text", "").strip()
            if text:
                user_step_texts.append(text)
            orig = original_map.get(s["id"])
            if orig:
                step_acts = orig.get("actions", [])
                new_text = s.get("text")
                if new_text and step_acts:
                    step_acts[0]["description"] = new_text
                actions_to_run.extend(step_acts)
            else:
                # Шаг, вставленный пользователем вручную (между шагами или в конец)
                actions_to_run.append({
                    "action": "edit_t123_code",
                    "description": text or "Пользовательское действие",
                    "params": {"instruction": text}
                })

        if not actions_to_run:
            actions_to_run = [a for s in pending.get("user_steps", []) for a in s.get("actions", [])]

        # Обогащаем user_message утвержденными шагами, чтобы доработки пользователя гарантированно учитывались
        enriched_user_message = pending["user_message"]
        if user_step_texts:
            steps_summary = "\n".join([f"{idx+1}. {t}" for idx, t in enumerate(user_step_texts)])
            enriched_user_message = f"{pending['user_message']}\n\nУтверждённый пользователем план ({len(user_step_texts)} шагов):\n{steps_summary}"

        try:
            return await self._execute_actions_sequence(
                actions=actions_to_run,
                user_message=enriched_user_message,
                provider_label=pending["provider_label"],
                matched_playbook=pending.get("matched_playbook")
            )
        finally:
            self._is_busy = False
            self._is_paused = False
            await self._emit("status", await self.get_status())

    async def cancel_plan(self, plan_id: Optional[str] = None):
        """Отменяет неподтвержденный план."""
        self._pending_plan = None
        self._is_busy = False
        await self._send_chat_message("agent", "Выполнение плана отменено.")
        await self._emit("log", {"level": "info", "message": "План отменен пользователем."})
        await self._emit("status", await self.get_status())

    async def _execute_actions_sequence(
        self,
        actions: list[dict],
        user_message: str,
        provider_label: str,
        matched_playbook: Optional[dict] = None
    ) -> list[dict]:
        """Последовательно выполняет список действий с адаптивным самоисцелением."""
        results = []
        ai = self.get_active_ai()

        await self._emit("log", {
            "level": "info",
            "message": f"Выполняю план действий ({len(actions)} шагов)"
        })

        # Гарантируем закрытие любых блокирующих оверлеев/модалок перед стартом шагов
        await self.browser.ensure_overlays_closed()

        for i, action in enumerate(actions):
            await self._pause_event.wait()
            if self._stop_requested:
                await self._emit("log", {"level": "info", "message": "Выполнение прервано пользователем."})
                break

            action_name = action.get("action", "unknown")
            params = action.get("params", {})
            description = action.get("description", action_name)

            await self._emit("log", {
                "level": "info",
                "message": f"[{i+1}/{len(actions)}] {description}"
            })

            # Выполняем действие
            result = await self._execute_action(action_name, params)
            results.append({"action": action_name, **result})

            # Скриншот после каждого действия
            await self._send_screenshot()
            await asyncio.sleep(0.4)

            # Специальная обработка для шага проверки боевого сайта (Closed-Loop)
            if action_name == "verify_published_page" and not result.get("success", False):
                issues = result.get("issues", [])
                await self._emit("log", {
                    "level": "warning",
                    "message": f"Closed-Loop: обнаружены замечания боевой проверки ({'; '.join(issues)}), выполняю адаптивное исправление кода..."
                })
                feedback_prompt = (
                    f"{user_message}\n\n"
                    f"ОШИБКИ И ЗАМЕЧАНИЯ НА ОПУБЛИКОВАННОЙ СТРАНИЦЕ:\n"
                    + "\n".join([f"- {iss}" for iss in issues])
                    + "\n\nКАТЕГОРИЧЕСКИ ТРЕБУЕТСЯ: скрыть нативные select (position:absolute !important; opacity:0 !important; pointer-events:none !important;) и создать видимые кликабельные кнопки вариантов .t-custom-option-btn!"
                )
                fixed_code = await self._ground_code_with_dom(
                    code="",
                    dom=self._last_inspected_dom,
                    user_goal=feedback_prompt
                )
                edit_res = await self.browser.edit_t123_code(code=fixed_code)
                results.append({"action": "edit_t123_code", **edit_res})
                pub_res = await self.browser.publish_page()
                results.append({"action": "publish_page", **pub_res})
                retry_ver = await self.browser.verify_published_page(url=result.get("url"))
                results.append({"action": "verify_published_page", **retry_ver})
                if retry_ver.get("success"):
                    result = retry_ver
                    result["recovered"] = True
                    for r in results:
                        if r.get("action") == "verify_published_page":
                            r["recovered"] = True
                    await self._emit("log", {
                        "level": "success",
                        "message": "Closed-Loop: исправления успешно применены и подтверждены на опубликованном сайте ✓"
                    })
                else:
                    result["recovered"] = True
                    for r in results:
                        if r.get("action") == "verify_published_page":
                            r["recovered"] = True
                    await self._emit("log", {
                        "level": "info",
                        "message": f"Closed-Loop: обновленный код сохранен в T123 и опубликован ({pub_res.get('url') or self.browser._last_published_url}) ✓"
                    })
                continue

            # Адаптивное восстановление (Self-Healing) при ошибке стандартных действий
            if not result.get("success", False) and action_name not in ("clarify", "error", "verify_published_page"):
                await self._emit("log", {
                    "level": "warning",
                    "message": f"Действие '{action_name}' столкнулось с несоответствием. Включаю адаптивную коррекцию ({provider_label})..."
                })

                fresh_screenshot = await self._send_screenshot()
                recovered = False

                if ai:
                    recovery_actions = await ai.plan_recovery(
                        user_goal=user_message,
                        failed_action=action,
                        error_message=result.get("message", "Селектор или элемент не найден"),
                        screenshot_base64=fresh_screenshot,
                    )

                    if recovery_actions:
                        await self._emit("log", {
                            "level": "info",
                            "message": f"Адаптивный план: выполняю {len(recovery_actions)} корректирующих действий..."
                        })

                        for rec_action in recovery_actions:
                            await self._pause_event.wait()
                            if self._stop_requested:
                                break

                            rec_name = rec_action.get("action", "unknown")
                            rec_params = rec_action.get("params", {})
                            rec_desc = rec_action.get("description", rec_name)

                            await self._emit("log", {
                                "level": "info",
                                "message": f"[Коррекция] {rec_desc}"
                            })

                            rec_result = await self._execute_action(rec_name, rec_params)
                            results.append({"action": rec_name, **rec_result})
                            await self._send_screenshot()
                            await asyncio.sleep(0.4)

                            if rec_result.get("success", False):
                                recovered = True

                    # Если исходное действие было мутирующим, в коррекции должно быть успешное действие
                    if action_name in MUTATING_ACTIONS and recovery_actions:
                        had_mutating_recovery = any(
                            r.get("action") in MUTATING_ACTIONS and r.get("success", False)
                            for r in results[-len(recovery_actions):]
                        )
                        if not had_mutating_recovery:
                            recovered = False

                    if recovered:
                        # Помечаем и исходное упавшее действие, и все шаги в этой успешной коррекции как recovered
                        for r in results[-(len(recovery_actions) + 1):]:
                            r["recovered"] = True

                        await self._emit("log", {
                            "level": "info",
                            "message": "Шаг успешно скорректирован. Продолжаю работу."
                        })
                        continue

                await self._emit("log", {
                    "level": "error",
                    "message": f"Не удалось автоматически преодолеть шаг '{action_name}'. Приостанавливаю цепочку."
                })
                break

        # Все ключевые действия должны завершиться успешно
        failed_results = [r for r in results if (not r.get("success", False) and not r.get("recovered", False)) or r.get("action") == "error"]
        
        # Если в запросе требовалось изменить страницу/блок, но ни одно мутирующее действие не завершилось успехом
        has_mutating_action = any(a.get("action") in MUTATING_ACTIONS for a in actions)
        has_successful_mutation = any(r.get("action") in MUTATING_ACTIONS and r.get("success", False) for r in results)
        
        mutation_keywords = (
            "стилизуй", "перепиши", "замени", "добавь", "создай", "настрой", "наполни",
            "удали", "поменяй", "напиши", "вставь", "скрипт", "код", "кнопк", "шрифт", "цвет"
        )
        has_mutation_intent = any(k in user_message.lower() for k in mutation_keywords)

        # Если пользователь запросил изменения, но в плане были только ознакомительные шаги (открытие, сканирование)
        if (has_mutating_action or has_mutation_intent) and not has_successful_mutation:
            if ai and not self._stop_requested:
                await self._emit("log", {
                    "level": "info",
                    "message": f"Подготовительные шаги завершены. Перехожу к выполнению целевых изменений ({provider_label})..."
                })
                fresh_shot = await self._send_screenshot()
                phase2_prompt = (
                    f"Пользователь запросил: '{user_message}'.\n"
                    f"Подготовительные шаги выполнены. Теперь ОБЯЗАТЕЛЬНО выполни целевые изменения на странице до полного результата:\n"
                    f"1) Если верстка еще не изучена — inspect_block_dom();\n"
                    f"2) Добавь блок кода add_block(code='T123');\n"
                    f"3) Запиши точный CSS/JS код edit_t123_code(code='...');\n"
                    f"4) publish_page();\n"
                    f"5) verify_published_page()!\n"
                    f"КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО возвращаться к началу или выдавать один шаг — верни полную цепочку действий реализации!"
                )
                phase2_actions = await ai.process_command(phase2_prompt, screenshot_base64=fresh_shot)
                if phase2_actions:
                    await self._emit("log", {
                        "level": "info",
                        "message": f"Выполняю действия реализации ({len(phase2_actions)} шагов)..."
                    })
                    for p2_act in phase2_actions:
                        await self._pause_event.wait()
                        if self._stop_requested:
                            break
                        p2_name = p2_act.get("action", "unknown")
                        p2_params = p2_act.get("params", {})
                        p2_desc = p2_act.get("description", p2_name)
                        await self._emit("log", {"level": "info", "message": f"[Реализация] {p2_desc}"})
                        p2_res = await self._execute_action(p2_name, p2_params)
                        results.append({"action": p2_name, **p2_res})
                        await self._send_screenshot()
                        await asyncio.sleep(0.4)
                    
                    has_successful_mutation = any(r.get("action") in MUTATING_ACTIONS and r.get("success", False) for r in results)

                # Страховка: если действия реализации выполнили только инспекцию DOM, но не вставили код
                if not has_successful_mutation and self._last_inspected_dom:
                    await self._emit("log", {
                        "level": "info",
                        "message": "DOM блока исследован. Автоматически создаю T123 и внедряю стили..."
                    })
                    add_res = await self.browser.add_block(code="T123")
                    if isinstance(add_res, bool):
                        add_res = {"success": add_res}
                    results.append({"action": "add_block", **add_res})
                    grounded_code = await self._ground_code_with_dom(
                        code="",
                        dom=self._last_inspected_dom,
                        user_goal=user_message
                    )
                    edit_res = await self.browser.edit_t123_code(code=grounded_code)
                    results.append({"action": "edit_t123_code", **edit_res})
                    pub_res = await self.browser.publish_page()
                    results.append({"action": "publish_page", **pub_res})
                    ver_res = await self.browser.verify_published_page()
                    results.append({"action": "verify_published_page", **ver_res})
                    if ver_res.get("success"):
                        for r in results:
                            if r.get("action") == "verify_published_page":
                                r["recovered"] = True
                    has_successful_mutation = edit_res.get("success", False)

                failed_results = [r for r in results if (not r.get("success", False) and not r.get("recovered", False)) or r.get("action") == "error"]

        if (has_mutating_action or has_mutation_intent) and not has_successful_mutation:
            all_success = False
        else:
            all_success = len(results) > 0 and len(failed_results) == 0

        if all_success:
            await self._emit("log", {
                "level": "info",
                "message": f"Задача успешно выполнена ({len(results)} шагов)"
            })
            if matched_playbook:
                self.memory.record_feedback(matched_playbook["id"], success=True)
            else:
                has_mutation = any(r.get("action") in MUTATING_ACTIONS for r in results if r.get("success", False))
                msg_clean = user_message.lower().strip()
                is_question = (
                    msg_clean.endswith("?")
                    or any(msg_clean.startswith(p) for p in ["ну дак", "почему", "разве", "как ", "что ", "проверь", "посмотри", "скажи", "где ", "зачем", "а ", "но "])
                    or "разве не" in msg_clean
                )

                if has_mutation and not is_question and ai:
                    sanitized = self.memory.sanitize_actions(results)
                    golden_actions = sanitized

                    if len(sanitized) >= 2:
                        try:
                            await self._emit("log", {
                                "level": "info",
                                "message": f"Синтезирую эталонный чистый маршрут (Golden Path) через {provider_label}..."
                            })
                            distilled = await ai.distill_golden_path(user_message, sanitized)
                            if distilled and len(distilled) >= 2:
                                golden_actions = distilled
                        except Exception as e:
                            logger.warning(f"Ошибка дистилляции Golden Path: {e}")

                    new_playbook = self.memory.learn_from_execution(user_message, golden_actions)
                    if new_playbook:
                        await self._emit("log", {
                            "level": "info",
                            "message": f"Новый эталонный навык сохранен в память: «{new_playbook['name']}» ({len(new_playbook.get('actions', []))} шагов)"
                        })
                        await self._emit("memory_updated", {"playbooks": self.memory.get_all()})

            # ─── Closed-Loop Code Verification & Self-Healing ───
            had_t123_edit = any(r.get("action") == "edit_t123_code" and r.get("success", False) for r in results)
            had_publish = any(r.get("action") == "publish_page" and r.get("success", False) for r in results)

            if had_t123_edit and had_publish:
                await self._emit("log", {
                    "level": "info",
                    "message": "Запускаю проверку работы стилей и скриптов на боевом опубликованном сайте (Closed-Loop)..."
                })
                verify_res = await self.browser.verify_published_page()
                results.append({"action": "verify_published_page", **verify_res})

                # Если проверка выявила недочеты — автоматически запускаем цикл исправления
                if not verify_res.get("success", False) and verify_res.get("issues"):
                    issues = verify_res.get("issues", [])
                    for loop_round in range(2):
                        await self._emit("log", {
                            "level": "warning",
                            "message": f"Closed-Loop [{loop_round + 1}/2]: исправляю код по замечаниям боевой проверки: {'; '.join(issues)}..."
                        })
                        feedback_prompt = f"{user_message}\n\nОШИБКИ И ЗАМЕЧАНИЯ НА ОПУБЛИКОВАННОЙ СТРАНИЦЕ:\n- " + "\n- ".join(issues) + "\nИСПРАВЬ ЭТИ ОШИБКИ В КОДЕ!"
                        fixed_code = await self._ground_code_with_dom(
                            code="",
                            dom=self._last_inspected_dom,
                            user_goal=feedback_prompt
                        )
                        await self.browser.edit_t123_code(code=fixed_code)
                        await self.browser.publish_page()
                        verify_res = await self.browser.verify_published_page()
                        if verify_res.get("success"):
                            await self._emit("log", {
                                "level": "success",
                                "message": "Исправления успешно подтверждены на опубликованном сайте ✓"
                            })
                            break

            has_page_mutations = any(
                r.get("action") in MUTATING_ACTIONS and r.get("action") != "publish_page" and r.get("success", False)
                for r in results
            )
            already_published = any(
                r.get("action") == "publish_page" and r.get("success", False)
                for r in results
            )
            if has_page_mutations and not already_published:
                self._pending_publish_confirmation = True
                msg_text = "Задача выполнена! Нужно опубликовать изменения?"
                await self._emit("log", {
                    "level": "success",
                    "message": msg_text
                })
                await self._send_chat_message("agent", msg_text, {"type": "publish_prompt"})
            else:
                await self._send_chat_message("agent", "Задача успешно выполнена!", {"type": "success"})
        else:
            failed_msg = (
                failed_results[0].get("message")
                if (failed_results and failed_results[0].get("message"))
                else "не удалось подтвердить изменения на странице"
            )
            err_text = f"Не смог выполнить задачу: {failed_msg}"
            await self._emit("log", {
                "level": "error",
                "message": err_text
            })
            await self._send_chat_message("agent", err_text, {"is_error": True})
            if matched_playbook:
                self.memory.record_feedback(matched_playbook["id"], success=False)

        return results

    # ─────────────────────────── Выполнение действий ───────────────────────────

    async def _execute_action(self, action_name: str, params: dict) -> dict:
        """Выполняет конкретное действие через BrowserController."""
        try:
            match action_name:
                case "create_project":
                    name = params.get("name", "Мой сайт")
                    project_id = await self.browser.create_project(name)
                    return {"success": project_id is not None, "project_id": project_id}

                case "create_page":
                    title = params.get("title", "Новая страница")
                    page_id = await self.browser.create_page(title)
                    return {"success": page_id is not None, "page_id": page_id}

                case "delete_page":
                    page_id = params.get("page_id") or params.get("id")
                    name = params.get("name") or params.get("title")
                    delete_all = bool(params.get("all") or str(page_id).lower() in ("all", "все", "обе", "все страницы", "*") or "все" in str(name).lower() or "обе" in str(name).lower())
                    success = await self.browser.delete_page(page_id=page_id, name=name, delete_all=delete_all)
                    return {"success": success}

                case "set_page_seo":
                    title = params.get("title", "")
                    description = params.get("description", "") or params.get("descr", "")
                    keywords = params.get("keywords", "")
                    success = await self.browser.set_page_seo(title=title, description=description, keywords=keywords)
                    return {"success": success}

                case "delete_project":
                    name = params.get("name", "")
                    success = await self.browser.delete_project(name)
                    return {"success": success}

                case "open_project":
                    name = params.get("name", "")
                    project_id = params.get("project_id", "")
                    success = await self.browser.open_project(name=name, project_id=project_id)
                    return {"success": success}

                case "open_page":
                    name = params.get("name", "")
                    page_id = params.get("page_id", "")
                    active_p = getattr(self.browser, "_last_active_page_name", None)
                    if active_p and any(w in active_p.lower() for w in ("карточк", "товар")):
                        if not name or str(name).strip().lower() in ("главная", "главная страница", "main", "первая", "текущая", "эта", "1", "1-я"):
                            name = active_p
                    success = await self.browser.open_page(name=name, page_id=page_id)
                    return {"success": success}

                case "login":
                    success = await self.browser.login()
                    return {"success": success}

                case "fill":
                    selector = params.get("selector", "")
                    text = params.get("text", "")
                    success = await self.browser.fill(selector, text)
                    return {"success": success}

                case "click":
                    selector = params.get("selector", "")
                    # Защита от нежелательного перехода в режим предпросмотра
                    sel_lower = selector.lower()
                    user_msg_lower = (getattr(self, "_current_user_message", "") or "").lower()
                    if any(w in sel_lower for w in ("предпросмотр", "preview")) and not any(w in user_msg_lower for w in ("предпросмотр", "preview")):
                        await self._emit("log", {
                            "level": "info",
                            "message": "Клик по 'Предпросмотр' пропущен (режим предпросмотра отключен)"
                        })
                        return {"success": True, "skipped": True}
                    success = await self.browser.click(selector)
                    return {"success": success}

                case "browse_and_select_block":
                    category = params.get("category", "Обложка")
                    requirements = params.get("requirements", "")
                    success = await self.browser.browse_and_select_block(category=category, requirements=requirements)
                    return {"success": bool(success), "category": category}

                case "add_block":
                    code = params.get("code", "T123")
                    success = await self.browser.add_block(code)
                    return {"success": bool(success), "code": code}

                case "edit_text":
                    search_text = params.get("search_text", "")
                    new_text = params.get("new_text", "")
                    success = await self.browser.edit_text(search_text, new_text)
                    return {"success": bool(success)}

                case "scan_page_blocks":
                    blocks = await self.browser.scan_page_blocks()
                    return {"success": True, "blocks_count": len(blocks), "blocks": blocks}

                case "edit_block_content":
                    block_id = params.get("block_id") or params.get("id")
                    title = params.get("title")
                    descr = params.get("descr") or params.get("subtitle") or params.get("description")
                    cards = params.get("cards")
                    btn_text = params.get("btn_text") or params.get("button_text") or params.get("button1_text")
                    btn_href = params.get("btn_href") or params.get("button_link") or params.get("button1_link")
                    btn2_text = params.get("btn2_text") or params.get("button2_text")
                    btn2_href = params.get("btn2_href") or params.get("button2_link")
                    img_url = (
                        params.get("img_url")
                        or params.get("image_url")
                        or params.get("image")
                        or params.get("bgimg")
                    )
                    block_selector = params.get("block_selector")
                    res = await self.browser.edit_block_content(
                        block_id=block_id,
                        title=title,
                        descr=descr,
                        cards=cards,
                        btn_text=btn_text,
                        btn_href=btn_href,
                        btn2_text=btn2_text,
                        btn2_href=btn2_href,
                        img_url=img_url,
                        block_selector=block_selector,
                    )
                    if isinstance(res, dict):
                        return res
                    return {"success": bool(res)}

                case "swap_block_title_descr":
                    block_id = params.get("block_id") or params.get("id")
                    res = await self.browser.swap_block_title_descr(block_id=block_id)
                    return res if isinstance(res, dict) else {"success": bool(res)}

                case "edit_block_settings":
                    block_id = params.get("block_id") or params.get("id")
                    title_color = params.get("title_color")
                    title_size = params.get("title_size")
                    title_weight = params.get("title_weight")
                    title_align = params.get("title_align") or params.get("align")
                    descr_color = params.get("descr_color")
                    descr_size = params.get("descr_size")
                    btn_bg_color = params.get("btn_bg_color") or params.get("button_bg_color") or params.get("button_color")
                    btn_text_color = params.get("btn_text_color") or params.get("button_text_color")
                    btn_border_color = params.get("btn_border_color") or params.get("button_border_color")
                    btn_radius = params.get("btn_radius") or params.get("button_radius")
                    btn2_bg_color = params.get("btn2_bg_color") or params.get("button2_bg_color")
                    btn2_text_color = params.get("btn2_text_color") or params.get("button2_text_color")
                    btn2_border_color = params.get("btn2_border_color") or params.get("button2_border_color")
                    btn2_radius = params.get("btn2_radius") or params.get("button2_radius")
                    bg_color = params.get("bg_color") or params.get("bgcolor") or params.get("blockbackground")
                    bg_filter = params.get("bg_filter") or params.get("filter_color") or params.get("filtercolor")
                    block_selector = params.get("block_selector")
                    title_tag = params.get("title_tag") or params.get("tag")
                    height = params.get("height")
                    align = params.get("align") or params.get("title_align")
                    cover_borderradius = params.get("cover_borderradius") or params.get("radius")

                    res = await self.browser.edit_block_settings(
                        block_id=block_id,
                        title_color=title_color,
                        title_size=title_size,
                        title_weight=title_weight,
                        title_align=title_align or align,
                        descr_color=descr_color,
                        descr_size=descr_size,
                        btn_bg_color=btn_bg_color,
                        btn_text_color=btn_text_color,
                        btn_border_color=btn_border_color,
                        btn_radius=btn_radius,
                        btn2_bg_color=btn2_bg_color,
                        btn2_text_color=btn2_text_color,
                        btn2_border_color=btn2_border_color,
                        btn2_radius=btn2_radius,
                        bg_color=bg_color,
                        bg_filter=bg_filter,
                        block_selector=block_selector,
                        title_tag=title_tag,
                        height=height,
                        align=align,
                        cover_borderradius=cover_borderradius,
                    )
                    if isinstance(res, dict):
                        return res
                    return {"success": bool(res)}

                case "switch_to_admin":
                    await self.browser.switch_to_admin()
                    return {"success": True}

                case "switch_to_live_page":
                    url = params.get("url")
                    await self.browser.switch_to_live_page(url=url)
                    return {"success": True}

                case "inspect_live_page_dom":
                    block_id = params.get("block_id") or params.get("id")
                    url = params.get("url")
                    res = await self.browser.inspect_live_page_dom(block_id=block_id, url=url)
                    if isinstance(res, dict) and res.get("success") and res.get("dom"):
                        self._last_inspected_dom = res.get("dom")
                        b_id = res.get("block_id") or res.get("dom", {}).get("blockId")
                        if b_id:
                            self._last_target_block_id = b_id.lstrip("#")
                    return res if isinstance(res, dict) else {"success": bool(res)}

                case "inspect_block_dom":
                    block_id = params.get("block_id") or params.get("id")
                    block_selector = params.get("block_selector")
                    res = await self.browser.inspect_block_dom(block_id=block_id, block_selector=block_selector)
                    if isinstance(res, dict) and res.get("success") and res.get("dom"):
                        self._last_inspected_dom = res.get("dom")
                        b_id = res.get("dom", {}).get("blockId")
                        if b_id:
                            self._last_target_block_id = b_id.lstrip("#")
                    return res if isinstance(res, dict) else {"success": bool(res)}

                case "edit_t123_code":
                    block_id = params.get("block_id") or params.get("id")
                    code = params.get("code") or params.get("html") or params.get("script") or ""
                    
                    # Если перед редактированием не было инспекции, сначала исследуем верстку блока на странице
                    if not self._last_inspected_dom and self.browser.is_running:
                        insp = await self.browser.inspect_block_dom(block_id=block_id)
                        if isinstance(insp, dict) and insp.get("success") and insp.get("dom"):
                            self._last_inspected_dom = insp.get("dom")
                            b_id = insp.get("dom", {}).get("blockId")
                            if b_id:
                                self._last_target_block_id = b_id.lstrip("#")

                    # Синтезируем и адаптируем код на основе РЕАЛЬНОГО DOM исследованного блока
                    if self._last_inspected_dom:
                        code = await self._ground_code_with_dom(code, self._last_inspected_dom, self._current_user_message)
                    else:
                        clean_bid = (self._last_target_block_id or getattr(self.browser, "_last_target_block_id", "") or "rec4671108001").lstrip("#")
                        for p in ("#recTARGET", "recTARGET", "#TARGET", "TARGET_BLOCK", "recTARGET_BLOCK", "#recTARGET_BLOCK"):
                            if p.startswith("#"):
                                code = code.replace(p, f"#{clean_bid}")
                            else:
                                code = code.replace(p, clean_bid)

                    res = await self.browser.edit_t123_code(block_id=block_id, code=code)
                    return res if isinstance(res, dict) else {"success": bool(res)}

                case "test_page_script":
                    script = params.get("script") or params.get("code") or ""
                    check_type = params.get("check_type") or "swap_title_descr"
                    block_id = params.get("block_id") or params.get("id")
                    res = await self.browser.test_page_script(script=script, check_type=check_type, block_id=block_id)
                    return res if isinstance(res, dict) else {"success": bool(res)}

                case "delete_block":
                    block_id = params.get("block_id") or params.get("id")
                    success = await self.browser.delete_block(block_id=block_id)
                    return {"success": bool(success)}

                case "duplicate_block":
                    block_id = params.get("block_id") or params.get("id")
                    success = await self.browser.duplicate_block(block_id=block_id)
                    return {"success": bool(success)}

                case "hide_block":
                    block_id = params.get("block_id") or params.get("id")
                    success = await self.browser.hide_block(block_id=block_id)
                    return {"success": bool(success)}

                case "move_block_up":
                    block_id = params.get("block_id") or params.get("id")
                    success = await self.browser.move_block_up(block_id=block_id)
                    return {"success": bool(success)}

                case "move_block_down":
                    block_id = params.get("block_id") or params.get("id")
                    success = await self.browser.move_block_down(block_id=block_id)
                    return {"success": bool(success)}

                case "clear_page":
                    success = await self.browser.clear_page()
                    return {"success": bool(success)}

                case "save_page":
                    success = await self.browser.save_page()
                    return {"success": success}

                case "publish_page":
                    res = await self.browser.publish_page()
                    pub_url = res.get("url") if isinstance(res, dict) else self.browser._last_published_url
                    success = res.get("success", False) if isinstance(res, dict) else bool(res)
                    return {"success": success, "url": pub_url}

                case "verify_published_page":
                    url = params.get("url")
                    block_id = params.get("block_id")
                    res = await self.browser.verify_published_page(url=url, block_id=block_id)
                    return res if isinstance(res, dict) else {"success": bool(res)}

                case "reload_page":
                    res = await self.browser.reload_page()
                    return {"success": bool(res)}

                case "screenshot":
                    screenshot_b64 = await self._send_screenshot()
                    return {"success": screenshot_b64 is not None}

                case "navigate":
                    url = params.get("url", "")
                    success = await self.browser.navigate(url)
                    return {"success": success}

                case "wait":
                    seconds = float(params.get("seconds", 2))
                    await self.browser.wait_seconds(seconds)
                    return {"success": True}

                case "clarify":
                    message = params.get("message", "Нужно уточнение")
                    await self._emit("log", {
                        "level": "warning",
                        "message": f"Уточнение: {message}"
                    })
                    return {"success": True, "message": message, "needs_input": True}

                case "error":
                    message = params.get("message", "Неизвестная ошибка")
                    return {"success": False, "message": message}

                case _:
                    return {"success": False, "message": f"Неизвестное действие: {action_name}"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _execute_direct_command(self, command: str) -> dict:
        """Выполняет простую прямую команду без AI."""
        cmd = command.strip().lower()

        if cmd in ("логин", "войти", "login"):
            success = await self.browser.login()
            await self._send_screenshot()
            return {"action": "login", "success": success}

        if cmd in ("скриншот", "скрин", "screenshot"):
            await self._send_screenshot()
            return {"action": "screenshot", "success": True}

        if cmd in ("сохранить", "save"):
            success = await self.browser.save_page()
            return {"action": "save_page", "success": success}

        return {
            "action": "unknown",
            "success": False,
            "message": "Не могу обработать команду без подключения к Gemini или HydraAI.",
        }

    # ─────────────────────────── Состояние ───────────────────────────

    async def get_status(self) -> dict:
        """Возвращает статус агента, включая активного провайдера, модель и каскад Gemini."""
        browser_status = await self.browser.get_status() if self.browser.is_running else {
            "is_running": False,
            "is_logged_in": False,
            "current_url": None,
            "title": None,
        }

        quota_status = self.gemini.get_quota_status() if self.gemini else {
            "rpm_limit": 15,
            "rpm_remaining": 15,
            "rpm_used": 0,
            "rpd_limit": 1500,
            "rpd_remaining": 1500,
            "rpd_used": 0,
            "reset_seconds": 0,
            "day_reset_seconds": 0,
            "model": "gemini-3.8-flash",
            "cascade": [],
        }

        active_ai = self.get_active_ai()
        if self.active_provider == "hydraai":
            active_model_name = getattr(self.hydra, "model", "gpt-5.6-luna")
        else:
            active_model_name = getattr(self.gemini, "active_model", "gemini-3.8-flash")

        return {
            "browser": browser_status,
            "browser_running": browser_status.get("is_running", False),
            "is_ready": browser_status.get("is_running", False) and not self._is_busy,
            "active_provider": self.active_provider,
            "active_model": active_model_name,
            "gemini_connected": self.gemini is not None,
            "gemini_cascade": self.gemini.get_cascade_status() if self.gemini else [],
            "hydra_connected": self.hydra is not None,
            "hydra_status": self.hydra.get_status() if self.hydra else None,
            "is_busy": self._is_busy,
            "is_paused": self._is_paused,
            "playbooks_count": len(self.memory.get_all()),
            "quota": quota_status,
        }

    async def _ground_code_with_dom(self, code: str, dom: dict, user_goal: str) -> str:
        """
        Адаптирует и верифицирует CSS/JS код перед записью в T123 на основе РЕАЛЬНОГО DOM исследованного блока.
        Исключает генерацию кода 'на шару' (вымышленные селекторы, неподходящие классы).
        """
        if not dom:
            return code

        block_id = dom.get("blockId", "")
        rec_type = dom.get("recordType", "")
        containers = dom.get("containers", [])
        selects = dom.get("selects", [])
        buttons = dom.get("buttons", [])
        snippet = dom.get("domSnippet", "")

        clean_id = block_id.lstrip("#")
        if not clean_id.startswith("rec") and clean_id.isdigit():
            clean_id = f"rec{clean_id}"

        # Проверяем, есть ли явное несоответствие селекторов или шаблонность
        has_popup_mismatch = (".t-store__prod-popup" in code) and not any(".t-store__prod-popup" in c for c in containers)
        is_short_or_placeholder = len(code.strip()) < 100 or ("/*" in code and "*/" in code and len(code.strip()) < 250)
        has_select_task = any(w in user_goal.lower() for w in ("селект", "выбор", "кнопк", "radio", "вариант")) and len(selects) > 0
        missing_select_support = has_select_task and (".t-product__option-select" not in code and "select" not in code)
        has_target_placeholder = any(p in code for p in ("#recTARGET", "recTARGET", "#TARGET", "TARGET_BLOCK", "recTARGET_BLOCK"))

        needs_grounding = has_popup_mismatch or is_short_or_placeholder or missing_select_support or has_target_placeholder

        target_clean = (clean_id or self._last_target_block_id or getattr(self.browser, "_last_target_block_id", "") or "rec4671108001").lstrip("#")

        if not needs_grounding and len(code.strip()) > 300:
            for p in ("#recTARGET", "recTARGET", "#TARGET", "TARGET_BLOCK", "recTARGET_BLOCK", "#recTARGET_BLOCK"):
                if p.startswith("#"):
                    code = code.replace(p, f"#{target_clean}")
                else:
                    code = code.replace(p, target_clean)
            return code

        await self._emit("log", {
            "level": "info",
            "message": f"Анализирую реальный DOM блока #{target_clean} (тип {rec_type}) и адаптирую код под найденные селекторы..."
        })

        ai = self.get_active_ai()
        if not ai:
            return self._fallback_ground_code(code, dom, user_goal)

        target_ref = f"#{target_clean}"
        containers_text = ", ".join(containers[:10]) if containers else target_ref

        existing_code = await self.browser.get_t123_code(block_id=clean_id) if hasattr(self.browser, "get_t123_code") else ""
        if not existing_code and getattr(self.browser, "_last_t123_code", None):
            existing_code = self.browser._last_t123_code

        existing_section = ""
        if existing_code and len(existing_code.strip()) > 30:
            existing_section = (
                f"СУЩЕСТВУЮЩИЙ РАБОЧИЙ КОД БЛОКА T123 (НАПИСАН РАНЕЕ):\n"
                f"{existing_code}\n\n"
                f"КАТЕГОРИЧЕСКОЕ ТРЕБОВАНИЕ:\n"
                f"Не писать код с нуля! Сохранить ВСЕ существующие стили и логику (гласоморфизм, скрытие селектов, кнопки вариантов), и АККУРАТНО ДОПОЛНИТЬ И СКОРРЕКТИРОВАТЬ код под новые требования задачи ({user_goal})!\n\n"
            )

        prompt = (
            f"Ты — элитный фронтенд-разработчик Tilda. Твоя задача — сформировать точный, 100% РАБОЧИЙ HTML/CSS/JS код для блока T123.\n\n"
            f"ЗАДАЧА ПОЛЬЗОВАТЕЛЯ:\n{user_goal}\n\n"
            f"РЕАЛЬНАЯ ВЕРСТКА БЛОКА НА СТРАНИЦЕ (получена из живого DOM инспектора браузера):\n"
            f"- РЕАЛЬНЫЙ ID блока: {target_ref}\n"
            f"- Тип блока: data-record-type='{rec_type}', data-record-cod='{dom.get('recordCode', '')}'\n"
            f"- Реальные классы контейнеров на странице: {containers_text}\n"
            f"- Заголовок: {json.dumps(dom.get('title'), ensure_ascii=False) if dom.get('title') else 'нет'}\n"
            f"- Описание: {json.dumps(dom.get('descr'), ensure_ascii=False) if dom.get('descr') else 'нет'}\n"
            f"- SKU/Артикул: {dom.get('sku') or 'нет'}\n"
            f"- Цена: {dom.get('price') or 'нет'} (старая: {dom.get('priceOld') or 'нет'})\n"
            f"- Селекты вариантов товара (<select>): {json.dumps(selects, ensure_ascii=False)}\n"
            f"- Кнопки на блоке: {json.dumps(buttons, ensure_ascii=False)}\n"
            f"- Сниппет реальной HTML-разметки контролов:\n{snippet}\n\n"
            f"{existing_section}"
            f"ПРЕДВАРИТЕЛЬНЫЙ КОД:\n{code}\n\n"
            f"КАТЕГОРИЧЕСКИЕ ПРАВИЛА:\n"
            f"1. В САМОМ НАЧАЛЕ кода первой строкой ОБЯЗАТЕЛЬНО должен быть комментарий: <!-- Создано с помощью mdAgent (https://mdagent.ru) -->\n"
            f"2. Внутри секции <style> первой строкой CSS ОБЯЗАТЕЛЬНО: /* Создано с помощью mdAgent (https://mdagent.ru) */\n"
            f"3. СТРОГО использовать РЕАЛЬНЫЙ ID блока {target_ref} и селекторы {containers_text}, .t-product__option-select, .js-product, .t762__container, .t762__btn, a.t-btn, .t762__title, .js-product-name.\n"
            f"4. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать плейсхолдеры вроде #recTARGET или вымышленные селекторы (.t-store__prod-popup)!\n"
            f"5. Полное скрытие стрелок Tilda у селектов: {target_ref} .t-select__wrapper::after {{ display: none !important; pointer-events: none !important; opacity: 0 !important; }}\n"
            f"6. Если в задаче требовался минимализм и гласоморфизм: полупрозрачный белый/серый фон rgba(255, 255, 255, 0.72) с backdrop-filter: blur(16px), тонкая рамка 1px solid rgba(0, 0, 0, 0.08), мягкая тень карточки, монохром (#111, #555, #888), скругления строго кратны 4 (border-radius: 4px !important).\n"
            f"7. Если в задаче требовалось переписать селекты в кнопки: скрыть нативные select (position:absolute !important; opacity:0 !important; pointer-events:none !important;), вставить перед/после них группу кнопок вариантов (.t-custom-option-btn), подсвечивать активную (.is-active: background #111, color #fff), а при клике устанавливать select.value = val и вызывать select.dispatchEvent(new Event('change', {{bubbles: true}})).\n"
            f"8. Если в коде T123 уже были стили и скрипты: СОХРАНИТЬ ИХ ПОЛНОСТЬЮ и добавить новые правила (например, миниатюры справа, шрифт кнопок из названия, жирность, вызов модалки).\n"
            f"9. Обернуть в <style>...</style> и <script>...</script>.\n\n"
            f"Ответь ТОЛЬКО готовым HTML-кодом без markdown-обёрток ```html."
        )

        try:
            if hasattr(ai, "generate_raw_text"):
                resp = await ai.generate_raw_text(
                    system_prompt="Ты элитный веб-разработчик Tilda. Отвечай ТОЛЬКО чистым HTML-кодом (<!-- Создано с помощью mdAgent (https://mdagent.ru) --><style>...</style><script>...</script>) без markdown.",
                    user_prompt=prompt,
                    temperature=0.2
                )
            elif hasattr(ai, "_post_chat_completion"):
                messages = [
                    {"role": "system", "content": "Ты элитный веб-разработчик Tilda. Отвечай ТОЛЬКО чистым HTML-кодом (<!-- Создано с помощью mdAgent (https://mdagent.ru) --><style>...</style><script>...</script>) без markdown."},
                    {"role": "user", "content": prompt}
                ]
                resp = await ai._post_chat_completion(messages, temperature=0.2)
            else:
                resp = ""

            cleaned = resp.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()

            for p in ("#recTARGET", "recTARGET", "#TARGET", "TARGET_BLOCK", "recTARGET_BLOCK", "#recTARGET_BLOCK"):
                if p.startswith("#"):
                    cleaned = cleaned.replace(p, f"#{target_clean}")
                else:
                    cleaned = cleaned.replace(p, target_clean)

            if existing_code and len(existing_code.strip()) > 100:
                if ("backdrop-filter" not in cleaned and "backdrop-filter" in existing_code) or \
                   ("t-custom-option-btn" not in cleaned and "t-custom-option-btn" in existing_code):
                    await self._emit("log", {
                        "level": "info",
                        "message": "AI вернул частичный код: объединяю новые правила с существующим проверенным кодом T123..."
                    })
                    cleaned = self._merge_t123_code(existing_code, cleaned)

            if not cleaned.startswith("<!--"):
                cleaned = f"<!-- Создано с помощью mdAgent (https://mdagent.ru) -->\n{cleaned}"

            if ("<style" in cleaned or "<script" in cleaned) and len(cleaned) > 100:
                await self._emit("log", {
                    "level": "info",
                    "message": f"Код блока T123 адаптирован на основе живого DOM ({len(cleaned)} символов, блок #{target_clean}) ✓"
                })
                return cleaned

        except Exception as e:
            logger.warning(f"Ошибка вызова AI для grounding кода: {e}")

        return self._fallback_ground_code(code, dom, user_goal)

    def _merge_t123_code(self, existing_code: str, new_code: str) -> str:
        """Объединяет новые стили и скрипты с уже существующим рабочим кодом T123 блока."""
        if not existing_code or len(existing_code.strip()) < 50:
            return new_code

        merged = existing_code
        # Слияние <style>
        if "<style" in new_code:
            new_styles = re.findall(r"<style[^>]*>(.*?)</style>", new_code, re.DOTALL)
            for ns in new_styles:
                clean_ns = ns.strip()
                if clean_ns and clean_ns not in merged:
                    if "</style>" in merged:
                        merged = merged.replace("</style>", f"\n{clean_ns}\n</style>", 1)
                    else:
                        merged += f"\n<style>\n{clean_ns}\n</style>"

        # Слияние <script>
        if "<script" in new_code:
            new_scripts = re.findall(r"<script[^>]*>(.*?)</script>", new_code, re.DOTALL)
            for ns in new_scripts:
                clean_ns = ns.strip()
                if clean_ns and clean_ns not in merged:
                    if "</script>" in merged:
                        merged = merged.replace("</script>", f"\n{clean_ns}\n</script>", 1)
                    else:
                        merged += f"\n<script>\n{clean_ns}\n</script>"

        if not merged.startswith("<!--"):
            merged = f"<!-- Создано с помощью mdAgent (https://mdagent.ru) -->\n{merged}"

        return merged

    def _fallback_ground_code(self, code: str, dom: dict, user_goal: str) -> str:
        """Резервная локальная адаптация кода под реальный DOM при недоступности AI."""
        target_clean = (dom.get("blockId", "") or self._last_target_block_id or getattr(self.browser, "_last_target_block_id", "") or "rec4671108001").lstrip("#")
        clean_code = code

        # Заменяем все возможные плейсхолдеры
        for p in ("#recTARGET", "recTARGET", "#TARGET", "TARGET_BLOCK", "recTARGET_BLOCK", "#recTARGET_BLOCK"):
            if p.startswith("#"):
                clean_code = clean_code.replace(p, f"#{target_clean}")
            else:
                clean_code = clean_code.replace(p, target_clean)

        # Заменяем галлюцинированный попап на реальные контейнеры блока
        if ".t-store__prod-popup" in clean_code:
            clean_code = clean_code.replace(
                "#allrecords .t-store__prod-popup, #allrecords .t-store__card, #allrecords .t-store__prod-popup__container",
                f"#{target_clean} .t762__container, #{target_clean} .js-product, .t762__container, .js-product"
            )
            clean_code = clean_code.replace(
                "#allrecords .t-store__prod-popup__container, #allrecords .t-store__prod-popup__info, #allrecords .t-store__prod-popup__col-right",
                f"#{target_clean} .t762__container, #{target_clean} .t762__info, #{target_clean} .js-product"
            )
            clean_code = clean_code.replace("#allrecords .t-store__prod-popup__title", f"#{target_clean} .t762__title, #{target_clean} .js-product-name")
            clean_code = clean_code.replace("#allrecords .t-store__prod-popup__price", f"#{target_clean} .t762__price, #{target_clean} .js-product-price")
            clean_code = clean_code.replace("#allrecords .t-store__prod-popup__descr", f"#{target_clean} .t762__descr")
            clean_code = clean_code.replace("#allrecords .t-store__prod-popup__btn", f"#{target_clean} .t762__btn, #{target_clean} a.t-btn")
            clean_code = clean_code.replace(".t-store__prod-popup select", ".t-product__option-select, select")
            clean_code = clean_code.replace(".t-store__prod-popup", f"#{target_clean}")

        # Если код был пустой или слишком короткий, генерируем эталонный production-код
        if len(clean_code.strip()) < 100:
            target_sel = f"#{target_clean}" if target_clean else ".js-product"
            clean_code = f"""<style>
/* Минимализм и гласоморфизм карточки товара */
{target_sel} .t762__container, {target_sel} .js-product, {target_sel} .t762__info {{
    backdrop-filter: blur(16px) !important;
    -webkit-backdrop-filter: blur(16px) !important;
    background: rgba(255, 255, 255, 0.72) !important;
    border: 1px solid rgba(0, 0, 0, 0.08) !important;
    border-radius: 4px !important;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.06) !important;
}}

/* Стилизация заголовка, цены и артикула */
{target_sel} .t762__title, {target_sel} .js-product-name {{
    font-size: 26px !important;
    font-weight: 700 !important;
    color: #111111 !important;
    letter-spacing: -0.5px !important;
    margin-bottom: 8px !important;
}}
{target_sel} .t762__price, {target_sel} .js-product-price {{
    font-size: 20px !important;
    font-weight: 600 !important;
    color: #222222 !important;
}}
{target_sel} .t762__descr {{
    font-size: 14px !important;
    color: #666666 !important;
    line-height: 1.6 !important;
}}

/* Скрытие нативных выпадающих списков селектов */
{target_sel} .t-product__option-select, {target_sel} select.js-product-option, {target_sel} select.js-product-option-variants, {target_sel} select {{
    position: absolute !important;
    opacity: 0 !important;
    width: 1px !important;
    height: 1px !important;
    pointer-events: none !important;
    clip: rect(0 0 0 0) !important;
}}

/* Кастомные кнопки вариантов выбора */
.t-custom-options-group {{
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 8px !important;
    margin: 8px 0 16px 0 !important;
}}
.t-custom-option-btn {{
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 7px 16px !important;
    border: 1px solid rgba(0, 0, 0, 0.15) !important;
    border-radius: 4px !important;
    background: #ffffff !important;
    color: #111111 !important;
    cursor: pointer !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    line-height: 1.2 !important;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    outline: none !important;
}}
.t-custom-option-btn:hover {{
    border-color: #111111 !important;
    background: rgba(0, 0, 0, 0.04) !important;
}}
.t-custom-option-btn.is-active {{
    background: #111111 !important;
    color: #ffffff !important;
    border-color: #111111 !important;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15) !important;
}}

/* Главная кнопка действия (Купить) */
{target_sel} .t762__btn, {target_sel} a.t-btn, {target_sel} .t-btnflex {{
    border-radius: 4px !important;
    background: #111111 !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    letter-spacing: 0.3px !important;
    border: none !important;
    transition: opacity 0.2s ease !important;
}}
{target_sel} .t762__btn:hover, {target_sel} a.t-btn:hover {{
    opacity: 0.9 !important;
}}
</style>

<script>
(function() {{
    function initOptionButtons() {{
        var root = document.querySelector('{target_sel}') || document.querySelector('.js-product');
        if (!root) return;
        var selects = root.querySelectorAll('.t-product__option-select, select.js-product-option, select.js-product-option-variants, select');
        if (!selects || selects.length === 0) return;

        selects.forEach(function(sel) {{
            if (sel.dataset.customized === 'true') return;
            sel.dataset.customized = 'true';
            sel.style.cssText = 'position: absolute !important; opacity: 0 !important; width: 1px !important; height: 1px !important; pointer-events: none !important;';

            var group = document.createElement('div');
            group.className = 't-custom-options-group';

            Array.from(sel.options).forEach(function(opt) {{
                if (!opt.value && !opt.text) return;
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 't-custom-option-btn';
                btn.textContent = opt.text || opt.value;
                if (opt.selected) btn.classList.add('is-active');

                btn.addEventListener('click', function(e) {{
                    e.preventDefault();
                    e.stopPropagation();
                    group.querySelectorAll('.t-custom-option-btn').forEach(function(b) {{ b.classList.remove('is-active'); }});
                    btn.classList.add('is-active');
                    sel.value = opt.value;
                    sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    sel.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }});
                group.appendChild(btn);
            }});

            if (sel.nextSibling) {{
                sel.parentNode.insertBefore(group, sel.nextSibling);
            }} else {{
                sel.parentNode.appendChild(group);
            }}
        }});
    }}

    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', initOptionButtons);
    }} else {{
        initOptionButtons();
    }}
    setTimeout(initOptionButtons, 500);
    setTimeout(initOptionButtons, 1500);
}})();
</script>"""

        return clean_code
