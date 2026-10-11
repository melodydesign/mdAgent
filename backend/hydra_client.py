"""
mdAgent — HydraAI Client
Клиент для взаимодействия с OpenAI-совместимым API HydraAI (модель GPT-5.6 Luna).
Поддерживает мультимодальные запросы (скриншоты Tilda), Self-Healing и дистилляцию Golden Path.
"""

import asyncio
import base64
import json
import logging
import re
from typing import Optional

import httpx

from backend.config import HYDRA_API_KEY, HYDRA_BASE_URL, HYDRA_MODEL
from backend.gemini_client import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class HydraClient:
    """Клиент для взаимодействия с HydraAI API (GPT-5.6 Luna)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or HYDRA_API_KEY
        if not self.api_key:
            raise ValueError("HYDRA_API_KEY не задан! Добавь его в .env файл.")
        self.base_url = (base_url or HYDRA_BASE_URL).rstrip("/")
        self.model = model or HYDRA_MODEL
        self.conversation_history: list[dict] = []
        logger.info(f"HydraAI client инициализирован (модель: {self.model}, base_url: {self.base_url})")

    def get_status(self) -> dict:
        """Возвращает метаданные и статус подключения к HydraAI."""
        return {
            "provider": "hydraai",
            "model": self.model,
            "connected": bool(self.api_key),
            "key_masked": f"{self.api_key[:12]}...{self.api_key[-4:]}" if len(self.api_key) > 16 else "***",
            "base_url": self.base_url,
        }

    def _parse_response(self, text: str) -> list[dict]:
        """Парсит JSON-ответ от модели, очищая markdown-блоки, огрехи кавычек и висячие запятые."""
        import ast

        cleaned = text.strip()
        # Очищаем markdown-разметку
        if "```" in cleaned:
            match_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
            if match_block:
                cleaned = match_block.group(1).strip()
            else:
                lines = [l for l in cleaned.split("\n") if not l.strip().startswith("```")]
                cleaned = "\n".join(lines).strip()

        match = re.search(r"(\[[\s\S]*\])", cleaned)
        if match:
            cleaned = match.group(1).strip()

        # 1. Стандартная попытка json.loads
        try:
            result = json.loads(cleaned)
            if isinstance(result, list):
                return result
            return [result]
        except json.JSONDecodeError:
            pass

        # 2. Попытка очистить висячие запятые и повторить
        try:
            fixed = re.sub(r",\s*([\]\}])", r"\1", cleaned)
            result = json.loads(fixed)
            if isinstance(result, list):
                return result
            return [result]
        except Exception:
            pass

        # 3. Попытка через ast.literal_eval (если модель использовала одинарные кавычки Python)
        try:
            py_dict = ast.literal_eval(cleaned)
            if isinstance(py_dict, list):
                return py_dict
            if isinstance(py_dict, dict):
                return [py_dict]
        except Exception:
            pass

        # 4. Поэлементное извлечение валидных объектов со сбалансированными скобками
        recovered = []
        i = 0
        while i < len(cleaned):
            if cleaned[i] == '{':
                depth = 0
                start = i
                in_string = False
                escape = False
                for j in range(i, len(cleaned)):
                    c = cleaned[j]
                    if escape:
                        escape = False
                        continue
                    if c == '\\':
                        escape = True
                        continue
                    if c == '"':
                        in_string = not in_string
                        continue
                    if not in_string:
                        if c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                            if depth == 0:
                                candidate = cleaned[start:j+1]
                                try:
                                    obj = json.loads(candidate)
                                    if isinstance(obj, dict) and "action" in obj:
                                        recovered.append(obj)
                                except Exception:
                                    try:
                                        obj = ast.literal_eval(candidate)
                                        if isinstance(obj, dict) and "action" in obj:
                                            recovered.append(obj)
                                    except Exception:
                                        pass
                                i = j
                                break
                i += 1
            else:
                i += 1

        if recovered:
            logger.info(f"Восстановлено {len(recovered)} действий из поврежденного ответа Luna")
            return recovered

        logger.error(f"Не удалось распарсить ответ HydraAI Luna: {text[:300]}")
        return [{
            "action": "error",
            "params": {"message": "Ошибка синтаксиса ответа от нейросети"},
            "description": "Ошибка обработки ответа от HydraAI Luna",
        }]

    async def _post_chat_completion(self, messages: list[dict], temperature: float = 0.2) -> str:
        """Выполняет POST-запрос к эндпоинту /chat/completions HydraAI."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        url = f"{self.base_url}/chat/completions"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                err_body = resp.text
                logger.error(f"HydraAI API error {resp.status_code}: {err_body}")
                raise RuntimeError(f"HydraAI API HTTP {resp.status_code}: {err_body}")

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content

    async def process_command(
        self,
        user_message: str,
        screenshot_base64: Optional[str] = None,
        playbook: Optional[dict] = None,
    ) -> list[dict]:
        """
        Обрабатывает команду пользователя через GPT-5.6 Luna с учетом скриншота и памяти.
        """
        user_content = []

        if playbook:
            playbook_info = (
                f"[ПАМЯТЬ АГЕНТА] НАЙДЕН ЭТАЛОННЫЙ ШАБЛОН ДЛЯ БАЗОВОЙ ОПЕРАЦИИ:\n"
                f"Название сценария: {playbook.get('name')}\n"
                f"Базовые шаги:\n{json.dumps(playbook.get('actions', []), ensure_ascii=False, indent=2)}\n\n"
                f"ПРАВИЛО: Возьми этот сценарий за основу, НО если запрос пользователя шире базового добавления "
                f"(например, требует наполнить блок текстами под определенную тему, добавить кнопки, заголовок или подзаголовок), "
                f"ОБЯЗАТЕЛЬНО дополни сценарий действием edit_block_content с соответствующими текстами! Не оставляй блок пустым!"
            )
            user_content.append({"type": "text", "text": playbook_info})

        if screenshot_base64:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"},
            })
            user_content.append({
                "type": "text",
                "text": f"Текущее состояние браузера показано на скриншоте выше.\n\nКоманда пользователя: {user_message}",
            })
        else:
            user_content.append({"type": "text", "text": user_message})

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        # Добавляем последние ходы истории диалога (только текстовую часть)
        for h in self.conversation_history[-6:]:
            messages.append(h)

        current_msg = {"role": "user", "content": user_content}
        messages.append(current_msg)

        for attempt in range(3):
            try:
                response_text = await self._post_chat_completion(messages, temperature=0.2)
                parsed = self._parse_response(response_text)
                if parsed:
                    # Сохраняем в историю диалога только валидные ответы с действиями
                    self.conversation_history.append({"role": "user", "content": user_message})
                    self.conversation_history.append({"role": "assistant", "content": response_text})
                return parsed
            except Exception as e:
                logger.warning(f"Попытка {attempt + 1}/3 обращения к HydraAI завершилась с ошибкой: {e}")
                if attempt < 2:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                return [{
                    "action": "error",
                    "params": {"message": f"Ошибка HydraAI: {str(e)}"},
                    "description": f"Ошибка при обращении к HydraAI: {str(e)}",
                }]

    # Псевдоним для совместимости
    plan_actions = process_command

    async def plan_recovery(
        self,
        user_goal: str,
        failed_action: dict,
        error_message: str,
        screenshot_base64: Optional[str] = None,
    ) -> list[dict]:
        """
        Генерирует корректирующие шаги при сбое действия (Self-Healing) через GPT-5.6 Luna.
        """
        recovery_prompt = (
            f"Предыдущее действие завершилось с ошибкой.\n"
            f"Цель пользователя: \"{user_goal}\"\n"
            f"Неудачное действие: {json.dumps(failed_action, ensure_ascii=False)}\n"
            f"Причина ошибки: \"{error_message}\"\n\n"
            f"Внимательно изучи текущий скриншот. Какое действие нужно предпринять прямо сейчас, "
            f"чтобы преодолеть затруднение и продолжить выполнение цели пользователя?\n"
            f"Например: если открыто модальное окно — заполни поле (fill) или нажми подтверждение (click).\n"
            f"Если цель уже достигнута — верни screenshot.\n"
            f"Ответь ТОЛЬКО JSON-массивом из 1-3 действий."
        )

        user_content = []
        if screenshot_base64:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"},
            })
        user_content.append({"type": "text", "text": recovery_prompt})

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            response_text = await self._post_chat_completion(messages, temperature=0.2)
            actions = self._parse_response(response_text)
            if actions and not (len(actions) == 1 and actions[0].get("action") == "error"):
                logger.info(f"Self-Healing (Luna): предложено {len(actions)} корректирующих действий")
                return actions
        except Exception as e:
            logger.warning(f"Ошибка Self-Healing в HydraClient: {e}")

        return []

    async def distill_golden_path(
        self,
        user_message: str,
        raw_actions: list[dict],
    ) -> list[dict]:
        """
        Дистиллирует цепочку действий в эталонный маршрут (Golden Path) через GPT-5.6 Luna.
        """
        prompt = f"""Ты — главный архитектор надёжной браузерной автоматизации Tilda.
Пользователь выполнил задачу: "{user_message}".
Вот действия, которые выполнялись (среди них могли быть лишние клики, промежуточные шаги, повторы):
{json.dumps(raw_actions, ensure_ascii=False, indent=2)}

Твоя задача:
1. Выдели САМЫЙ КОРОТКИЙ, ЧИСТЫЙ и БЕЗОПАСНЫЙ эталонный маршрут (Golden Path) для достижения ЭТОГО ЖЕ результата с первого раза.
2. Убери все лишние клики, промежуточные ожидания, дубли и костыли.
3. В конце обязательно добавь действие screenshot для фиксации результата.
4. Идеальный рецепт должен содержать от 2 до 5 простых и понятных шагов.

Доступные действия: scan_page_blocks, edit_block_content, swap_block_title_descr, edit_block_settings, delete_block, duplicate_block, hide_block, move_block_up, move_block_down, browse_and_select_block, add_block, inspect_block_dom, inspect_live_page_dom, switch_to_admin, switch_to_live_page, edit_t123_code, test_page_script, navigate, click, fill, wait, screenshot, login, save_page, publish_page, verify_published_page, open_project, open_page.

Ответь ТОЛЬКО валидным JSON-массивом действий без markdown и пояснений:
[
  {{"action": "...", "params": {{...}}, "description": "..."}}
]
"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            response_text = await self._post_chat_completion(messages, temperature=0.1)
            parsed = self._parse_response(response_text)
            if parsed and not (len(parsed) == 1 and parsed[0].get("action") == "error"):
                logger.info(f"[Маршрут] Golden Path (Luna) успешно синтезирован: {len(parsed)} шагов")
                return parsed
        except Exception as e:
            logger.warning(f"Ошибка синтеза Golden Path в HydraClient: {e}")

        return []

    async def analyze_screenshot(self, screenshot_base64: str, question: str) -> str:
        """Анализирует скриншот через GPT-5.6 Luna."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"}},
                    {"type": "text", "text": question},
                ],
            }
        ]
        try:
            return await self._post_chat_completion(messages, temperature=0.3)
        except Exception as e:
            logger.error(f"Ошибка analyze_screenshot в HydraClient: {e}")
            return f"Ошибка анализа скриншота: {str(e)}"

    async def generate_raw_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """Генерирует произвольный текст (например, точный CSS/JS код) через GPT-5.6 Luna."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return await self._post_chat_completion(messages, temperature=temperature)

    def reset_history(self):
        """Очищает историю диалога."""
        self.conversation_history.clear()
        logger.info("История диалога с HydraAI сброшена.")
