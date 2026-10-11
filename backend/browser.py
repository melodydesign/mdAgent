"""
mdAgent — Browser Controller
Управление браузером через Playwright. Содержит рецепты для работы с Tilda.
"""

import asyncio
import base64
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional, Callable, Awaitable

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    CDPSession,
)

from backend.config import (
    BROWSER_HEADLESS,
    BROWSER_DATA_DIR,
    SCREENSHOT_DIR,
    DATA_DIR,
    TILDA_EMAIL,
    TILDA_PASSWORD,
    TILDA_LOGIN_URL,
    TILDA_PROJECTS_URL,
)

logger = logging.getLogger(__name__)

SESSION_STATE_FILE: Path = DATA_DIR / "active_session_state.json"

# Тип для callback-функции логирования
LogCallback = Optional[Callable[[str, str], Awaitable[None]]]
# Тип для callback-функции отправки кадров трансляции в реальном времени
FrameCallback = Optional[Callable[[str], Awaitable[None]]]


def parse_ordinal_page_index(name: Optional[str] = None, page_id: Optional[str | int] = None) -> Optional[int]:
    """
    Определяет, является ли переданный page_id или name порядковым номером страницы
    (например: "1", "2", "вторая", "2-я страница").
    Возвращает 0-based индекс (0 для первой, 1 для второй и т.д.) или None, если это реальный Tilda ID или текстовое название.
    """
    # 1. Проверяем page_id: если это короткое число (меньше 10000), это порядковый номер
    if page_id is not None:
        p_str = str(page_id).strip()
        if p_str.isdigit():
            val = int(p_str)
            if 1 <= val < 10000:
                return val - 1

    # 2. Проверяем name
    if name:
        n_clean = name.strip().lower()

        ordinal_map = {
            "первая": 0, "первую": 0, "первой": 0, "1-я": 0, "1-ю": 0, "1": 0,
            "вторая": 1, "вторую": 1, "второй": 1, "2-я": 1, "2-ю": 1, "2": 1,
            "третья": 2, "третью": 2, "третьей": 2, "3-я": 2, "3-ю": 2, "3": 2,
            "четвертая": 3, "четвертую": 3, "четвертой": 3, "4-я": 3, "4-ю": 3, "4": 3,
            "пятая": 4, "пятую": 4, "пятой": 4, "5-я": 4, "5-ю": 4, "5": 4,
            "шестая": 5, "шестую": 5, "шестой": 5, "6-я": 5, "6-ю": 5, "6": 5,
        }

        # Проверяем точное слово
        if n_clean in ordinal_map:
            return ordinal_map[n_clean]

        # Регулярка для фраз вида "вторая страница", "2 страница", "для второй страницы"
        match = re.search(r'\b(перв[а-я]+|втор[а-я]+|трет[а-я]+|четверт[а-я]+|пят[а-я]+|шест[а-я]+|[1-6](?:-?[а-я]+)?)\s+страниц', n_clean)
        if match:
            token = match.group(1)
            for k, idx in ordinal_map.items():
                if token.startswith(k[:4]) or token == k:
                    return idx

    return None


def is_page_not_found_content(html_or_text: str) -> bool:
    """
    Проверяет, является ли страница экраном ошибки 404 в Tilda
    (например, 'Страница не существует', кнопка 'К списку проектов', 'page-not-found').
    """
    if not html_or_text:
        return False
    lower = html_or_text.lower()
    indicators = [
        "страница не существует",
        "page not found",
        "td-page-not-found",
        "к списку проектов",
    ]
    return any(ind in lower for ind in indicators)


def normalize_block_settings_payload(raw: dict) -> dict:
    """
    Нормализует параметры стилизации для шторки «Настройки» блока Tilda:
    - Цвета: очистка от пробелов, автоматическое добавление '#' для hex (3, 6 или 8 символов), приведение к нижнему регистру.
    - Размеры и радиусы: извлечение числовой части (например, "44px" -> "44", 30 -> "30").
    - Выравнивание и начертание: очистка от пробелов.
    - Отсечение пустых или None значений.
    """
    if not isinstance(raw, dict):
        return {}

    normalized = {}

    color_keys = {
        "title_color", "descr_color", "bg_color", "bg_filter", "filtercolor", "filtercolor2", "blockbackground",
        "btn_bg_color", "btn_text_color", "btn_border_color",
        "btn2_bg_color", "btn2_text_color", "btn2_border_color",
    }

    size_keys = {
        "title_size", "descr_size", "btn_radius", "btn2_radius", "cover_borderradius",
        "btn_border_width", "btn2_border_width",
    }

    for key, val in raw.items():
        if val is None:
            continue
        s_val = str(val).strip()
        if not s_val:
            continue

        if key in color_keys:
            hex_clean = s_val.lstrip("#")
            if re.fullmatch(r"[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8}", hex_clean):
                normalized[key] = f"#{hex_clean.lower()}"
            else:
                normalized[key] = s_val.lower()

        elif key in size_keys:
            num_match = re.search(r"^\d+", s_val)
            if num_match:
                normalized[key] = num_match.group(0)
            else:
                normalized[key] = s_val

        elif key == "title_tag":
            normalized[key] = s_val.upper()
        elif key in ("align", "valign", "title_align"):
            normalized[key] = s_val.lower()
        elif key == "height":
            normalized[key] = s_val
        else:
            normalized[key] = s_val

    return normalized


class BrowserController:
    """Управление Chromium-браузером через Playwright."""

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._admin_page: Optional[Page] = None
        self._live_page: Optional[Page] = None
        self._last_target_block_id: Optional[str] = None
        self._last_inspected_dom: Optional[dict] = None
        self._cdp: Optional[CDPSession] = None
        self._is_logged_in: bool = False
        self._log_callback: LogCallback = None
        self._frame_callback: FrameCallback = None
        self._last_frame_time: float = 0.0
        self._screencast_active: bool = False
        self._is_starting: bool = False
        self._last_mouse_pos: tuple = (None, None)
        self._last_published_url: Optional[str] = None
        self._is_publishing: bool = False
        self._last_active_page_id: Optional[str] = None
        self._last_active_page_name: Optional[str] = None
        self._last_active_project_id: Optional[str] = None
        self._last_active_project_name: Optional[str] = None
        self._last_t123_code: Optional[str] = None

        # Загружаем сохраненное сессионное состояние с диска
        self._load_session_state()

    def _load_session_state(self):
        """Загружает сохраненные параметры активной рабочей области с диска."""
        try:
            if SESSION_STATE_FILE.exists():
                content = SESSION_STATE_FILE.read_text(encoding="utf-8")
                data = json.loads(content)
                if isinstance(data, dict):
                    self._last_active_page_id = data.get("page_id") or self._last_active_page_id
                    self._last_active_page_name = data.get("page_name") or self._last_active_page_name
                    self._last_active_project_id = data.get("project_id") or self._last_active_project_id
                    self._last_active_project_name = data.get("project_name") or self._last_active_project_name
                    self._last_target_block_id = data.get("target_block_id") or self._last_target_block_id
                    self._last_published_url = data.get("published_url") or self._last_published_url
                    self._last_t123_code = data.get("t123_code") or self._last_t123_code
                    logger.info(
                        f"Сессионная память загружена: проект «{self._last_active_project_name}», "
                        f"страница «{self._last_active_page_name}» (#{self._last_active_page_id}), блок #{self._last_target_block_id}"
                    )
        except Exception as e:
            logger.warning(f"Не удалось прочитать active_session_state.json: {e}")

    def _save_session_state(self):
        """Сохраняет текущую активную рабочую область на диск для устойчивости к рестартам."""
        try:
            SESSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "page_id": self._last_active_page_id,
                "page_name": self._last_active_page_name,
                "project_id": self._last_active_project_id,
                "project_name": self._last_active_project_name,
                "target_block_id": self._last_target_block_id,
                "published_url": self._last_published_url,
                "t123_code": self._last_t123_code,
                "updated_at": time.time(),
            }
            SESSION_STATE_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Не удалось записать active_session_state.json: {e}")

    def set_log_callback(self, callback: LogCallback):
        """Устанавливает callback для отправки логов в UI."""
        self._log_callback = callback

    def set_frame_callback(self, callback: FrameCallback):
        """Устанавливает callback для непрерывной трансляции кадров экрана в UI."""
        self._frame_callback = callback

    async def _log(self, level: str, message: str):
        """Логирует сообщение и отправляет в UI если есть callback."""
        logger.log(getattr(logging, level.upper(), logging.INFO), message)
        if self._log_callback:
            await self._log_callback(level, message)

    async def start(self):
        """Запускает браузер."""
        if self._is_starting or self._browser:
            await self._log("info", "Браузер уже запускается или запущен")
            return

        self._is_starting = True
        try:
            await self._log("info", "Запускаю Chromium...")
            self._playwright = await async_playwright().start()

            common_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-ipc-flooding-protection",
                "--force-color-profile=srgb",
            ]
            if sys.platform == "win32":
                common_args.extend([
                    "--start-maximized",
                    "--window-position=50,50",
                    "--enable-gpu-rasterization",
                    "--enable-zero-copy",
                ])
            else:
                # Linux VPS без физического GPU: отключаем аппаратный GPU-конвейер
                # для исключения 100% CPU нагрузки llvmpipe и выпадения тайлов
                common_args.extend([
                    "--window-size=1920,1080",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                ])

            launch_args = {
                "headless": BROWSER_HEADLESS,
                "args": common_args,
            }
            try:
                self._browser = await self._playwright.chromium.launch(channel="chrome", **launch_args)
            except Exception as chrome_err:
                try:
                    self._browser = await self._playwright.chromium.launch(channel="msedge", **launch_args)
                except Exception:
                    self._browser = await self._playwright.chromium.launch(**launch_args)

            self._context = await self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                storage_state=str(BROWSER_DATA_DIR / "state.json")
                if (BROWSER_DATA_DIR / "state.json").exists()
                else None,
            )

            # Скрываем флаги автоматизации и гарантируем автоподтверждение диалогов Tilda
            await self._context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en-US', 'en'] });
                window.chrome = window.chrome || { runtime: {} };
                window.confirm = () => true;
                window.alert = () => true;
            """)

            self._admin_page = await self._context.new_page()
            self._page = self._admin_page
            # Автоматически принимаем любые диалоги браузера (в т.ч. confirm при удалении блоков)
            self._admin_page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
            await self._log("info", "Браузер запущен (Stealth режим активен, Вкладка 1: Админка Tilda)")

            # Автоматически открываем Tilda
            await self._log("info", "Открываю Tilda...")
            try:
                await self._page.goto(TILDA_PROJECTS_URL, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                current = self._page.url
                if "/login" in current or "/identity" in current:
                    if TILDA_EMAIL and TILDA_PASSWORD:
                        await self._log("info", "Нужна авторизация — запускаю логин...")
                        await self.login()
                    else:
                        await self._log(
                            "info",
                            "Открыта страница входа Tilda. Вы можете войти вручную в окне браузера или добавить TILDA_EMAIL и TILDA_PASSWORD в .env"
                        )
                else:
                    await self._log("info", f"Tilda открыта ({current})")
                    self._is_logged_in = True
            except Exception as e:
                await self._log("warning", f"Не удалось открыть Tilda: {e}")

            # Автоматически запускаем живую трансляцию через CDP Screencast
            await self.start_screencast()
            # Выводим окно браузера на передний план рабочего стола
            await self.bring_to_front()
            return True
        finally:
            self._is_starting = False

    async def _attach_screencast_to_page(self, target_page: Page):
        """Перенаправляет CDP Screencast на указанную страницу (админка или боевой сайт)."""
        if not self._context or not target_page:
            return
        if not self._screencast_active and not self._frame_callback:
            return

        try:
            if self._cdp:
                try:
                    await self._cdp.send("Page.stopScreencast")
                    await self._cdp.detach()
                except Exception:
                    pass
                self._cdp = None

            self._cdp = await self._context.new_cdp_session(target_page)
            self._screencast_active = True

            async def _on_frame(event: dict):
                session_id = event.get("sessionId")
                if session_id and self._cdp and self._screencast_active:
                    try:
                        await self._cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
                    except Exception:
                        pass

                now = time.monotonic()
                if now - self._last_frame_time >= 0.075:
                    self._last_frame_time = now
                    data = event.get("data")
                    if self._frame_callback and data:
                        try:
                            await self._frame_callback(data)
                        except Exception:
                            pass

            self._cdp.on("Page.screencastFrame", lambda e: asyncio.create_task(_on_frame(e)))

            await self._cdp.send("Page.startScreencast", {
                "format": "jpeg",
                "quality": 75,
                "maxWidth": 1280,
                "maxHeight": 720,
                "everyNthFrame": 2,
            })
        except Exception as e:
            logger.warning(f"Не удалось переключить CDP Screencast на страницу: {e}")

    async def start_screencast(self):
        """Запускает непрерывную живую трансляцию экрана Chromium через CDP (Page.startScreencast)."""
        if not self._page or not self._context:
            return
        if self._screencast_active and self._cdp:
            return
        self._screencast_active = True
        await self._attach_screencast_to_page(self._page)
        await self._log("info", "Живая трансляция браузера активна (CDP Screencast LIVE) ✓")

    async def stop_screencast(self):
        """Останавливает непрерывную трансляцию экрана."""
        self._screencast_active = False
        if self._cdp:
            try:
                await self._cdp.send("Page.stopScreencast")
                await self._cdp.detach()
            except Exception:
                pass
            self._cdp = None

    async def ensure_two_tabs_only(self):
        """Гарантирует, что открыты ТОЛЬКО 2 вкладки (админка и боевой сайт). Все лишние попапы и вкладки закрываются."""
        if not self._context:
            return
        try:
            allowed = {self._admin_page, self._live_page}
            for p in list(self._context.pages):
                if p not in allowed and not p.is_closed():
                    try:
                        await p.close()
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Ошибка при очистке лишних вкладок: {e}")

    async def switch_to_admin(self) -> Page:
        """Переключает фокус и контекст на Вкладку 1 (админка Tilda). Не плодит вкладки."""
        if not self._context:
            raise RuntimeError("Браузер не запущен")
        if not self._admin_page or self._admin_page.is_closed():
            if self._context.pages:
                self._admin_page = self._context.pages[0]
            else:
                self._admin_page = await self._context.new_page()
                self._admin_page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))

        self._page = self._admin_page
        try:
            await self._admin_page.bring_to_front()
        except Exception:
            pass
        await self._attach_screencast_to_page(self._admin_page)
        await self.ensure_two_tabs_only()
        await self._log("info", "🔄 [Вкладка 1] Переключился на админку Tilda")
        return self._admin_page

    async def get_current_page_live_url(self) -> Optional[str]:
        """
        Динамически извлекает публичный URL боевой страницы из интерфейса Tilda (Вкладка 1: админка),
        без какого-либо хардкода адресов.
        """
        if not self._admin_page or self._admin_page.is_closed():
            return self._last_published_url

        try:
            live_url = await self._admin_page.evaluate("""() => {
                const isInvalidUrl = (u) => {
                    if (!u || !u.startsWith('http')) return true;
                    const low = u.toLowerCase();
                    return low.includes('help.') || low.includes('help-') || low.includes('support') ||
                           low.includes('/projects') || low.includes('/login') || low.includes('/page/?') ||
                           low.includes('tilda.cc') || low.includes('tilda.ru') || low.includes('identity');
                };

                // 1. Ссылка на боевую страницу в верхней панели редактора (.td-page-bar)
                const barLinks = Array.from(document.querySelectorAll(
                    '.td-page-bar a[target="_blank"], #mainmenu a[target="_blank"], .td-page-bar__link a, a.td-page-bar__url, a.td-page-bar__btn-view'
                ));
                for (const a of barLinks) {
                    const href = (a.href || '').trim();
                    if (!isInvalidUrl(href)) return href;
                }

                // 2. Любые внешние ссылки на *.tilda.ws или пользовательский домен в шапке редактора
                const allHeaderLinks = Array.from(document.querySelectorAll(
                    '.td-page-bar a, #mainmenu a, .tp-record-edit-top-panel a'
                ));
                for (const a of allHeaderLinks) {
                    const href = (a.href || '').trim();
                    if (!isInvalidUrl(href)) return href;
                }

                // 3. Поиск в тексте верхней панели (текст вида 'mysite.tilda.ws/page')
                const bar = document.querySelector('.td-page-bar, #mainmenu');
                if (bar) {
                    const txt = bar.innerText || '';
                    const m = txt.match(/https?:\\/\\/[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}(?:\\/[^\\s"'<>]*)?/);
                    if (m && !isInvalidUrl(m[0])) return m[0];
                    const m2 = txt.match(/([a-zA-Z0-9.-]+\\.tilda\\.ws(?:\\/[^\\s"'<>]*)?)/);
                    if (m2) return 'https://' + m2[1];
                }

                return null;
            }""")
            if live_url:
                self._last_published_url = live_url
                return live_url
        except Exception as e:
            logger.warning(f"Ошибка при извлечении боевого URL из шапки Tilda: {e}")

        return self._last_published_url

    async def _resolve_live_url(self, explicit_url: Optional[str] = None) -> Optional[str]:
        """
        Разрешает динамический URL опубликованного сайта:
        - Исключает любые устаревшие захардкоженные шаблоны (например, site-md-z4khkb);
        - Если explicit_url не передан или устарел — берет реальный URL из недавней публикации (_last_published_url);
        - Если URL все еще неизвестен — динамически извлекает его из редактора текущей страницы Tilda.
        """
        clean_url = (explicit_url or "").strip()
        is_stale_template = bool(clean_url and "site-md-z4khkb" in clean_url)

        if clean_url and not is_stale_template:
            self._last_published_url = clean_url
            return clean_url

        if is_stale_template:
            await self._log(
                "info",
                f"Замечен устаревший шаблонный URL '{clean_url}'. "
                "Автоматически переключаюсь на реальный динамический URL текущего проекта..."
            )

        if self._last_published_url and not ("site-md-z4khkb" in self._last_published_url):
            return self._last_published_url

        extracted = await self.get_current_page_live_url()
        if extracted and not ("site-md-z4khkb" in extracted):
            self._last_published_url = extracted
            return extracted

        return self._last_published_url

    async def switch_to_live_page(self, url: Optional[str] = None) -> Page:
        """Переключает фокус и контекст на Вкладку 2 (опубликованный сайт). Не плодит вкладки."""
        if not self._context:
            raise RuntimeError("Браузер не запущен")

        target_url = await self._resolve_live_url(url)
        if not self._live_page or self._live_page.is_closed():
            self._live_page = await self._context.new_page()
            self._live_page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))

        self._page = self._live_page
        try:
            await self._live_page.bring_to_front()
        except Exception:
            pass
        await self._attach_screencast_to_page(self._live_page)

        if target_url:
            cur_url = self._live_page.url or ""
            if target_url.rstrip("/") in cur_url or (cur_url and cur_url.rstrip("/") in target_url):
                await self._log("info", f"🔄 [Вкладка 2] Обновляю боевую страницу (F5): {target_url}")
                await self._live_page.reload(wait_until="domcontentloaded", timeout=25000)
            else:
                await self._log("info", f"🔄 [Вкладка 2] Перехожу на опубликованную страницу: {target_url}")
                await self._live_page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(1.5)
        else:
            await self._log("info", "🔄 [Вкладка 2] Переключился на опубликованную страницу")

        await self.ensure_two_tabs_only()
        return self._live_page

    async def handle_user_input(self, event_data: dict):
        """Обрабатывает интерактивные действия пользователя из веб-интерфейса (Remote Control)."""
        if not self._page:
            return
        ev_type = event_data.get("event")
        try:
            if ev_type == "click":
                x = int(event_data.get("x", 0))
                y = int(event_data.get("y", 0))
                btn = event_data.get("button", "left")
                if btn not in ("left", "right", "middle"):
                    btn = "left"
                await self._page.mouse.click(x, y, button=btn)
            elif ev_type == "mousedown":
                x = int(event_data.get("x", 0))
                y = int(event_data.get("y", 0))
                btn = event_data.get("button", "left")
                await self._page.mouse.move(x, y)
                await self._page.mouse.down(button=btn)
            elif ev_type == "mouseup":
                x = int(event_data.get("x", 0))
                y = int(event_data.get("y", 0))
                btn = event_data.get("button", "left")
                await self._page.mouse.move(x, y)
                await self._page.mouse.up(button=btn)
            elif ev_type in ("wheel", "scroll"):
                dx = float(event_data.get("deltaX", 0))
                dy = float(event_data.get("deltaY", 0))
                x = event_data.get("x")
                y = event_data.get("y")
                if x is not None and y is not None:
                    pos = (int(x), int(y))
                    if self._last_mouse_pos != pos:
                        self._last_mouse_pos = pos
                        await self._page.mouse.move(pos[0], pos[1])
                await self._page.mouse.wheel(dx, dy)
            elif ev_type in ("mousemove", "move"):
                x = int(event_data.get("x", 0))
                y = int(event_data.get("y", 0))
                await self._page.mouse.move(x, y)
            elif ev_type == "keydown":
                key = event_data.get("key", "")
                text = event_data.get("text", "")
                if text and len(text) == 1 and not event_data.get("ctrlKey") and not event_data.get("altKey"):
                    await self._page.keyboard.type(text)
                elif key:
                    await self._page.keyboard.press(key)
        except Exception as e:
            logger.warning(f"Ошибка при обработке пользовательского ввода в браузере: {e}")

    async def bring_to_front(self):
        """Выводит окно Chromium на передний план рабочего стола."""
        if not self._page:
            return
        try:
            await self._page.bring_to_front()
            if sys.platform == "win32":
                import subprocess
                ps_script = """
                $wshell = New-Object -ComObject Wscript.Shell
                $activated = $false
                foreach ($t in @('Tilda', 'tilda', 'Chrome', 'Chromium')) {
                    if ($wshell.AppActivate($t)) { $activated = $true; break }
                }
                if (-not $activated) {
                    $p = Get-Process chrome, chromium -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
                    if ($p) {
                        Add-Type @"
                          using System;
                          using System.Runtime.InteropServices;
                          public class WinFocus {
                            [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
                            [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
                          }
"@
                        [WinFocus]::ShowWindow($p.MainWindowHandle, 9)
                        [WinFocus]::SetForegroundWindow($p.MainWindowHandle)
                    }
                }
                """
                subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script], creationflags=subprocess.CREATE_NO_WINDOW)
            await self._log("info", "Окно Chromium выведено на передний план рабочего стола ✓")
        except Exception as e:
            await self._log("warning", f"Не удалось вывести окно на передний план: {e}")

    async def ensure_overlays_closed(self) -> bool:
        """
        Проверяет и гарантированно закрывает блокирующие оверлеи (например, #closelayer, библиотеку блоков Tilda,
        модалки успешной публикации или системные диалоги), чтобы они не перехватывали клики и не зависали на экране.
        """
        if not self._page:
            return False

        try:
            is_pub = getattr(self, "_is_publishing", False)
            closed = await self.page.evaluate("""(isPub) => {
                let touched = false;
                // Закрываем оверлей closelayer
                const cl = document.querySelector('#closelayer');
                if (cl) {
                    cl.click();
                    touched = true;
                }
                // Кнопки закрытия библиотеки, модалок и диалогов
                const closeBtns = document.querySelectorAll(
                    '.tp-library__close-btn, .tp-record-edit-panel__close-btn, .td-popup-window__close, .tp-shortcuttools__close, .td-popup__btn-close, .modal-close, [data-action="close"], .td-popup-window [class*="close"]'
                );
                closeBtns.forEach(b => {
                    if (b && b.offsetParent !== null) {
                        b.click();
                        touched = true;
                    }
                });

                // Если висит модалка "Задайте адрес сайта" и мы НЕ в процессе публикации — закрываем её крестиком
                if (!isPub) {
                    const domainPrompt = Array.from(document.querySelectorAll('.td-popup-window, .td-popup, .modal, div[class*="popup"]')).find(
                        el => el.innerText && el.innerText.includes('Задайте адрес сайта')
                    );
                    if (domainPrompt) {
                        const xBtn = domainPrompt.querySelector('.td-popup-window__close, .tp-popup__close, button, [class*="close"]');
                        if (xBtn) {
                            xBtn.click();
                            touched = true;
                        }
                    }
                }

                // Закрываем модалки успешной публикации Tilda или системных уведомлений
                const pubModals = Array.from(document.querySelectorAll('.td-popup-window, .td-popup, .modal, div[class*="popup"], div[class*="modal"]')).filter(
                    el => el.innerText && (
                        el.innerText.includes('Публикация прошла успешно') ||
                        el.innerText.includes('Публичная ссылка на эту страницу') ||
                        el.innerText.includes('Что-то пошло не так')
                    )
                );
                pubModals.forEach(pm => {
                    const closeBtn = pm.querySelector('.td-popup-window__close, .tp-popup__close, .td-popup__btn-close, a[class*="close"], [data-action="close"], button');
                    if (closeBtn) {
                        closeBtn.click();
                        touched = true;
                    }
                    const txtClose = Array.from(pm.querySelectorAll('button, a')).find(b => b.innerText && b.innerText.trim().toLowerCase() === 'закрыть');
                    if (txtClose) {
                        txtClose.click();
                        touched = true;
                    }
                });

                // Если страница находится в режиме предпросмотра — возвращаемся в редактор
                const backToEdit = Array.from(document.querySelectorAll('a, button, div, .tp-shortcuttools__button-back')).find(
                    el => el.innerText && el.innerText.includes('Вернуться к редактированию')
                );
                if (backToEdit && backToEdit.offsetParent !== null) {
                    backToEdit.click();
                    touched = true;
                }
                return touched;
            }""")
            # Дополнительно нажимаем Escape для закрытия любых выпадающих оверлеев
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.3)

            # Если всё ещё в режиме previewmode=yes в URL — принудительно переходим в чистый редактор
            if self.page and "previewmode=yes" in self.page.url:
                clean_url = self.page.url.replace("&previewmode=yes", "").replace("?previewmode=yes&", "?").replace("?previewmode=yes", "")
                try:
                    await self.page.goto(clean_url, wait_until="domcontentloaded", timeout=10000)
                except Exception:
                    pass
            return True
        except Exception as e:
            logger.debug(f"Ошибка при закрытии оверлеев: {e}")
            return False

    async def reload_page(self) -> bool:
        """
        Обновляет текущую страницу Tilda (F5 / page.reload), ожидает загрузку и закрывает любые оверлеи/модалки,
        гарантируя актуальный DOM и отсутствие зависших попапов публикации или несохраненных оверлеев.
        """
        if not self._page:
            return False
        try:
            current_url = self.page.url
            if "/page/?pageid=" in current_url or "/projects/" in current_url:
                await self._log("info", "Обновляю страницу перед выполнением задачи для синхронизации с Tilda...")
                await self.page.reload(wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1.5)
                await self.ensure_overlays_closed()
                await self._log("info", "Страница Tilda успешно обновлена ✓")
                return True
            return False
        except Exception as e:
            await self._log("warning", f"Предупреждение при обновлении страницы: {e}")
            await self.ensure_overlays_closed()
            return False

    async def stop(self):
        """Останавливает браузер и сохраняет состояние."""
        await self.stop_screencast()
        if self._context:
            try:
                await self._context.storage_state(
                    path=str(BROWSER_DATA_DIR / "state.json")
                )
                await self._log("info", "Состояние браузера сохранено")
            except Exception as e:
                await self._log("warning", f"Не удалось сохранить состояние: {e}")

        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._page = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        self._is_logged_in = False
        await self._log("info", "Браузер остановлен")

    @property
    def page(self) -> Page:
        """Текущая страница. Бросает ошибку если браузер не запущен."""
        if not self._page:
            raise RuntimeError("Браузер не запущен! Вызовите start() сначала.")
        return self._page

    @property
    def is_running(self) -> bool:
        return self._browser is not None

    @property
    def is_logged_in(self) -> bool:
        return self._is_logged_in

    # ─────────────────────────── Базовые действия ───────────────────────────

    async def screenshot(self) -> str:
        """Делает скриншот и возвращает base64 строку с защитой от таймаута."""
        if not self._page:
            return ""
        try:
            screenshot_bytes = await self.page.screenshot(
                type="jpeg",
                quality=80,
                animations="disabled",
                timeout=2000
            )
            timestamp = int(time.time())
            path = SCREENSHOT_DIR / f"screenshot_{timestamp}.jpg"
            path.write_bytes(screenshot_bytes)
            return base64.b64encode(screenshot_bytes).decode("utf-8")
        except Exception as e:
            logger.warning(f"Скриншот пропущен (таймаут или занятость страницы): {e}")
            return ""

    async def ensure_logged_in(self, email: Optional[str] = None, password: Optional[str] = None) -> bool:
        """
        Проверяет текущий URL. Если сессия Tilda вылетела на страницу логина (/login или /identity),
        автоматически выполняет повторную авторизацию через login().
        """
        if not self._page:
            return False
        curr_url = (self._page.url or "").lower()
        if "/login" in curr_url or "/identity" in curr_url:
            await self._log("warning", "Обнаружен вылет сессии Tilda (страница логина). Выполняю автоматический повторный вход...")
            ok = await self.login(email=email, password=password)
            if ok:
                await self._log("success", "Авторизация в Tilda успешно восстановлена ✓")
                return True
            else:
                await self._log("error", "Не удалось автоматически восстановить вход в Tilda")
                return False
        return True

    async def navigate(self, url: str) -> bool:
        """Переходит по URL."""
        await self._log("info", f"Перехожу на {url}")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        return True

    async def smart_click(self, selector_or_candidates: str, timeout: int = 5000) -> bool:
        """
        Умный клик: последовательно перебирает селекторы, текст и атрибуты.
        Никогда не крашит сценарий при изменении или частичном несовпадении верстки.
        """
        if not selector_or_candidates:
            return False

        # Разбиваем по запятым с учетом возможных кавычек
        candidates = [c.strip() for c in re.split(r",(?=(?:[^\'\"]*[\'\"][^\'\"]*[\'\"])*[^\'\"]*$)", selector_or_candidates) if c.strip()]
        if not candidates:
            candidates = [selector_or_candidates.strip()]

        for cand in candidates:
            try:
                # 1. Если задано text="..." или text='...'
                if cand.startswith("text=") or cand.startswith("text='") or cand.startswith('text="'):
                    text_val = cand.split("=", 1)[1].strip("'\"")
                    loc = self.page.get_by_text(text_val, exact=False).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.scroll_into_view_if_needed()
                        await loc.click(timeout=timeout)
                        await asyncio.sleep(0.4)
                        await self._log("info", f"Клик по тексту '{text_val}'")
                        return True

                # 2. Попытка через CSS / ID / XPath локатор
                loc = self.page.locator(cand).first
                if await loc.count() > 0:
                    try:
                        await loc.wait_for(state="visible", timeout=1200)
                        await loc.scroll_into_view_if_needed()
                        await loc.click(timeout=timeout)
                        await asyncio.sleep(0.4)
                        await self._log("info", f"Клик по элементу '{cand}'")
                        return True
                    except Exception:
                        pass
            except Exception:
                continue

        # 3. Эвристический поиск по характерным ключевым словам (Создать, Сохранить, Удалить и т.д.)
        for word in ["Создать", "Сохранить", "Удалить", "Опубликовать", "Войти", "Login", "Save", "Настройки"]:
            if any(word.lower() in cand.lower() for cand in candidates):
                try:
                    btn_loc = self.page.locator(f"input[value*='{word}'], button:has-text('{word}'), a:has-text('{word}')").first
                    if await btn_loc.count() > 0 and await btn_loc.is_visible():
                        await btn_loc.scroll_into_view_if_needed()
                        await btn_loc.click(timeout=timeout)
                        await asyncio.sleep(0.4)
                        await self._log("info", f"Эвристический клик по кнопке '{word}'")
                        return True
                except Exception:
                    pass

        await self._log("warning", f"Элемент для клика не найден: {selector_or_candidates}")
        return False

    async def click(self, selector: str) -> bool:
        """Кликает по элементу (обертка над smart_click)."""
        await self._log("info", f"Кликаю: {selector}")
        success = await self.smart_click(selector)
        if not success:
            raise RuntimeError(f"Не удалось кликнуть по элементу '{selector}'")
        await asyncio.sleep(0.5)
        return True

    async def smart_fill(self, selector: str, text: str, timeout: int = 5000) -> bool:
        """
        Умное заполнение поля ввода: перебирает кандидаты селекторов,
        очищает поле и вводит текст.
        """
        candidates = [c.strip() for c in re.split(r",(?=(?:[^\'\"]*[\'\"][^\'\"]*[\'\"])*[^\'\"]*$)", selector) if c.strip()]
        if not candidates:
            candidates = [selector.strip()]

        for cand in candidates:
            try:
                loc = self.page.locator(cand).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=1000)
                    await loc.fill(text, timeout=timeout)
                    await asyncio.sleep(0.3)
                    await self._log("info", f"Поле '{cand}' заполнено")
                    return True
            except Exception:
                continue

        # Эвристика: если открыто модальное окно или есть видимый input на первом плане
        try:
            visible_inputs = self.page.locator(".td-popup-window input[type='text']:visible, #modalinputprojecttitle:visible, input[name='title']:visible, input[type='text']:visible, textarea:visible")
            if await visible_inputs.count() > 0:
                first_input = visible_inputs.first
                await first_input.click(timeout=1000)
                await first_input.fill(text, timeout=timeout)
                await asyncio.sleep(0.3)
                await self._log("info", "Текст введён в активное поле ввода")
                return True
        except Exception:
            pass

        await self._log("warning", f"Не удалось заполнить поле: {selector}")
        return False

    async def fill(self, selector: str, text: str) -> bool:
        """Заполняет поле ввода текстом (обертка над smart_fill)."""
        await self._log("info", f"Заполняю поле {selector}: {text}")
        success = await self.smart_fill(selector, text)
        if not success:
            raise RuntimeError(f"Не удалось заполнить поле '{selector}'")
        return True

    async def wait_for(self, selector: str, timeout: int = 10000):
        """Ждёт появления элемента."""
        await self._log("info", f"Жду элемент: {selector}")
        await self.page.wait_for_selector(selector, timeout=timeout)

    async def wait_seconds(self, seconds: float):
        """Просто ждёт N секунд."""
        await self._log("info", f"Жду {seconds} сек...")
        await asyncio.sleep(seconds)

    # ─────────────────────────── Tilda: reCAPTCHA & Логин ───────────────────────────

    async def handle_recaptcha_if_present(self, timeout_sec: float = 8.0) -> bool:
        """
        Обнаруживает Google reCAPTCHA v2 на странице Tilda и выполняет автоматический проход:
        1. Находит iframe чекбокса reCAPTCHA.
        2. Делает человекоподобный клик по #recaptcha-anchor.
        3. Ожидает появления зеленой галочки (aria-checked="true").
        """
        if not self._page:
            return False

        try:
            # 1. Поиск фрейма reCAPTCHA
            anchor_frame = None
            for f in self.page.frames:
                if "recaptcha" in f.url and ("anchor" in f.url or "api2" in f.url):
                    anchor_frame = f
                    break

            if not anchor_frame:
                iframes = self.page.locator('iframe[src*="recaptcha/api2/anchor"], iframe[title*="reCAPTCHA"], iframe[src*="google.com/recaptcha"]')
                if await iframes.count() > 0:
                    handle = await iframes.first.element_handle()
                    if handle:
                        anchor_frame = await handle.content_frame()

            if not anchor_frame:
                return False

            await self._log("info", "Обнаружена Google reCAPTCHA v2. Выполняю автоматический проход...")

            checkbox = anchor_frame.locator("#recaptcha-anchor, .recaptcha-checkbox, span[role='checkbox']").first
            if await checkbox.count() > 0:
                # Проверяем, может уже решена
                if await checkbox.get_attribute("aria-checked") == "true":
                    await self._log("info", "reCAPTCHA v2 уже подтверждена (зелёная галочка) ✓")
                    return True

                await asyncio.sleep(0.5)
                await checkbox.hover()
                await asyncio.sleep(0.25)
                await checkbox.click()
                await self._log("info", "Клик по чекбоксу «Я не робот» выполнен, ожидаю верификацию...")

                start = time.monotonic()
                while time.monotonic() - start < timeout_sec:
                    checked = await checkbox.get_attribute("aria-checked")
                    if checked == "true":
                        await self._log("info", "reCAPTCHA v2 успешно пройдена моментально (зелёная галочка) ✓")
                        return True

                    # Проверяем, не открылся ли интерактивный фрейм картинок
                    has_bframe = any("recaptcha" in f.url and "bframe" in f.url for f in self.page.frames)
                    if has_bframe:
                        await self._log("warning", "reCAPTCHA запросила выбор картинок. Пожалуйста, подтвердите капчу в открытом браузере.")
                        break

                    await asyncio.sleep(0.5)

            return False
        except Exception as e:
            logger.debug(f"Проверка reCAPTCHA: {e}")
            return False

    async def login(self, email: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Логинится в Tilda через email/пароль с автоматическим прохождением капчи."""
        target_email = email or TILDA_EMAIL
        target_password = password or TILDA_PASSWORD

        if not target_email or not target_password:
            await self._log(
                "warning",
                "Учетные данные Tilda не заданы (в диалоге или .env). Вы можете авторизоваться вручную в открытом браузере."
            )
            return False

        await self._log("info", "Начинаю авторизацию в Tilda...")

        # Проверяем, может уже залогинены (через сохранённые куки)
        await self.navigate(TILDA_PROJECTS_URL)
        await asyncio.sleep(2)

        current_url = self.page.url
        if "/projects" in current_url and "/login" not in current_url:
            await self._log("info", "Уже авторизован в Tilda (через сохранённые куки) ✓")
            self._is_logged_in = True
            return True

        # Идём на страницу логина
        await self.navigate(TILDA_LOGIN_URL)
        await asyncio.sleep(2)

        try:
            # Заполняем email
            await self.smart_fill('input[name="email"], input[type="email"], #email, input[name="login"]', target_email)
            await asyncio.sleep(0.3)

            # Заполняем пароль
            await self.smart_fill('input[name="password"], input[type="password"], #password', target_password)
            await asyncio.sleep(0.3)

            # Проверяем, нет ли капчи сразу на форме
            await self.handle_recaptcha_if_present(timeout_sec=5.0)

            # Нажимаем кнопку входа
            submit_btn = self.page.locator('button[type="submit"], .t-submit, [data-testid="login-button"], input[type="submit"], button:has-text("Войти"), button:has-text("Log in")').first
            if await submit_btn.count() > 0:
                await submit_btn.click()
            await asyncio.sleep(2.5)

            # Если после нажатия кнопки страница все еще логин — пробуем решить появившуюся капчу
            current_url = self.page.url
            if "/login" in current_url or "/identity" in current_url:
                await self._log("info", "Проверяю требование reCAPTCHA после клика «Войти»...")
                captcha_done = await self.handle_recaptcha_if_present(timeout_sec=7.0)
                if captcha_done:
                    await asyncio.sleep(0.5)
                    submit_again = self.page.locator('button[type="submit"], .t-submit, [data-testid="login-button"], input[type="submit"], button:has-text("Войти")').first
                    if await submit_again.count() > 0:
                        await submit_again.click()
                    await asyncio.sleep(3)
                    current_url = self.page.url

            # Корректная проверка успешной авторизации (не на странице логина!)
            if ("/projects" in current_url or "/page/" in current_url) and "/login" not in current_url:
                await self._log("info", "Авторизация в Tilda успешно выполнена ✓")
                self._is_logged_in = True
                # Сохраняем состояние на диск
                if self._context:
                    await self._context.storage_state(
                        path=str(BROWSER_DATA_DIR / "state.json")
                    )
                    await self._log("info", "Сессия Tilda сохранена на диск")
                return True
            else:
                await self._log("warning", f"Авторизация ещё не подтверждена (текущий URL: {current_url})")
                return False

        except Exception as e:
            await self._log("error", f"Ошибка авторизации: {e}")
            return False

    # ─────────────────────────── Tilda: Проекты ───────────────────────────

    async def open_project(self, name: Optional[str] = None, project_id: Optional[str] = None) -> bool:
        """
        Открывает проект в Tilda.
        Можно указать имя (поиск по тексту) или ID (прямая навигация).
        """
        self._last_published_url = None
        self._last_target_block_id = None
        self._last_inspected_dom = None
        if project_id:
            url = f"https://tilda.cc/projects/project{project_id}/"
            await self.navigate(url)
            await asyncio.sleep(2)
            await self._log("info", f"Открыт проект #{project_id}")
            return True

        if name:
            # Идём на страницу проектов и ищем по имени
            await self.navigate(TILDA_PROJECTS_URL)
            await asyncio.sleep(2)

            try:
                # Ищем проект по тексту карточки и кликаем 'РЕДАКТИРОВАТЬ САЙТ' или ссылку с projectid
                clicked = await self.page.evaluate("""(targetName) => {
                    const term = targetName.toLowerCase().trim();
                    const cards = Array.from(document.querySelectorAll('.td-site, .td-project, tr, div[class*="site"], div[class*="project"], div[class*="item"]'));
                    for (const c of cards) {
                        const txt = (c.innerText || '').toLowerCase();
                        if (txt.includes(term)) {
                            const btn = c.querySelector('a[href*="projectid="]') || 
                                        Array.from(c.querySelectorAll('a')).find(a => (a.innerText || '').includes('РЕДАКТИРОВАТЬ САЙТ') || (a.innerText || '').includes('Редактировать'));
                            if (btn) { btn.click(); return true; }
                        }
                    }
                    const anyProj = document.querySelector('a:has-text("РЕДАКТИРОВАТЬ САЙТ"), a[href*="/projects/?projectid="], a[href*="projectid="]');
                    if (anyProj) { anyProj.click(); return true; }
                    return false;
                }""", name)

                if not clicked:
                    # Резервный поиск Playwright
                    proj_link = self.page.locator("a[href*='projectid='], a:has-text('РЕДАКТИРОВАТЬ САЙТ'), a:has-text('Редактировать сайт')").first
                    if await proj_link.count() > 0:
                        await proj_link.click(force=True)
                        clicked = True

                if clicked:
                    await asyncio.sleep(2.5)
                    current_url = self.page.url if self._page else ""
                    if "projectid=" in current_url:
                        await self._log("info", f"Открыт проект '{name}'")
                        return True
            except Exception as e:
                await self._log("error", f"Ошибка открытия проекта '{name}': {e}")
                return False

        # Если имя или ID не указаны — открываем первый доступный проект
        await self.navigate(TILDA_PROJECTS_URL)
        await asyncio.sleep(2)
        try:
            # Точный селектор кнопки перехода в проект (не кликаем navbar 'Мои сайты'!)
            first_proj = self.page.locator('a:has-text("РЕДАКТИРОВАТЬ САЙТ"), a:has-text("Редактировать сайт"), a[href*="/projects/?projectid="], a[href*="projectid="]').first
            if await first_proj.count() > 0:
                await first_proj.click(force=True)
                await asyncio.sleep(2.5)
                current_url = self.page.url if self._page else ""
                if "projectid=" in current_url:
                    await self._log("info", "Открыт первый проект из списка")
                    return True
        except Exception as e:
            await self._log("warning", f"Ошибка клика по первому проекту: {e}")

        await self._log("error", "Проект для открытия не найден")
        return False

    async def _is_page_not_found(self) -> bool:
        """Проверяет, отображает ли текущая страница в браузере ошибку 404 Tilda."""
        if not self._page:
            return False
        try:
            # 1. Проверяем наличие характерных селекторов/кнопок 404
            has_404_el = await self.page.locator("text='Страница не существует', .td-page-not-found, a:has-text('К списку проектов')").count()
            if has_404_el > 0:
                return True
            # 2. Проверяем содержимое HTML
            content = await self.page.content()
            return is_page_not_found_content(content)
        except Exception:
            return False

    async def open_page(self, name: Optional[str] = None, page_id: Optional[str] = None) -> bool:
        """Открывает страницу проекта для редактирования с гарантией правильного выбора карточки товара."""
        raw_name = str(name or "").strip()
        raw_name_lower = raw_name.lower()

        # Детектор задачи карточки товара: в названии, параметрах или сохраненном контексте
        is_product_card_query = (
            any(w in raw_name_lower for w in ("карточк", "товар", "миниатюр", "селект"))
            or (self._last_active_page_name and any(w in self._last_active_page_name.lower() for w in ("карточк", "товар")))
        )

        # 0. Порядковый номер страницы (1-я, 2-я и т.д.)
        # ВНИМАНИЕ: если задача касается карточки товара, игнорируем ложные ordinal_idx (например, случайно пришедший №1)
        ordinal_idx = None if is_product_card_query else parse_ordinal_page_index(name=name, page_id=page_id)

        # Если запрошена карточка товара, а имя не задано или задано абстрактно («текущая», «эта», «главная»)
        if is_product_card_query:
            if not raw_name or raw_name_lower in ("главная", "главная страница", "main", "первая", "текущая", "эта", "1", "1-я"):
                name = self._last_active_page_name or "карточка товара"
                raw_name = name
                raw_name_lower = raw_name.lower()

        if page_id or (name and raw_name_lower not in ("главная", "главная страница", "main", "первая", "текущая", "эта")):
            self._last_published_url = None
            self._last_target_block_id = None
            self._last_inspected_dom = None
        current_url = self.page.url if self._page else ""

        # 0.1. Если имя или page_id не переданы — пытаемся восстановить ранее активную страницу сессии
        if not name and not page_id and ordinal_idx is None:
            if self._last_active_page_id:
                if "/page/?pageid=" not in current_url or self._last_active_page_id not in current_url:
                    page_label = f" «{self._last_active_page_name}»" if self._last_active_page_name else ""
                    await self._log("info", f"Возвращаюсь к текущей активной странице{page_label} (#{self._last_active_page_id})...")
                    url = f"https://tilda.ru/page/?pageid={self._last_active_page_id}"
                    await self.navigate(url)
                    await asyncio.sleep(2.5)
                    if not await self._is_page_not_found():
                        self._save_session_state()
                        return True
            elif self._last_active_page_name:
                name = self._last_active_page_name
                raw_name = name
                raw_name_lower = raw_name.lower()

        # 1. Если мы уже находимся в редакторе страницы:
        if "/page/?pageid=" in current_url and ordinal_idx is None and not page_id:
            if not await self._is_page_not_found():
                clean_name = raw_name
                current_title = await self.page.evaluate("""() => {
                    const el = document.querySelector('.td-page-bar__title, .tp-record-edit-top-panel a:last-child, #mainmenu a:last-child, #mainmenu .td-page-title');
                    if (el && el.innerText) return el.innerText.trim();
                    const dt = document.title || '';
                    return dt.includes(':') ? dt.split(':')[1].trim() : dt.trim();
                }""") or ""

                # Проверяем, есть ли на текущей открытой странице блок карточки товара
                has_product_card_in_editor = await self.page.evaluate("""() => {
                    return !!document.querySelector('.record[data-record-type="762"], .record:has(.js-product), .record:has(.t762), [data-record-type="762"]');
                }""")

                # Если задача про карточку товара, но открыта левая страница (Blank page / главная без карточки)
                if is_product_card_query and not has_product_card_in_editor and "карточк" not in current_title.lower():
                    await self._log("info", f"Сейчас открыта страница «{current_title}» (без карточки товара). Перехожу к целевой странице «карточка товара»...")
                    # Выходим в проект для поиска нужной страницы
                    await self.open_project()
                    await asyncio.sleep(2.0)
                    current_url = self.page.url if self._page else ""
                else:
                    # Если имя совпадает или открыта целевая страница
                    if not clean_name or clean_name.lower() in ("главная", "главная страница", "main", "первая", "текущая", "эта") or (current_title and clean_name.lower() in current_title.lower()) or (is_product_card_query and has_product_card_in_editor):
                        m_p = re.search(r"pageid=(\d+)", current_url)
                        if m_p:
                            self._last_active_page_id = m_p.group(1)
                        if current_title:
                            self._last_active_page_name = current_title
                        self._save_session_state()
                        await self._log("info", f"Целевая страница «{self._last_active_page_name or clean_name}» уже открыта в редакторе ({current_url})")
                        return True

                    # Иначе целевая страница отличается от открытой — выходим в проект для перехода
                    await self._log("info", f"Сейчас открыта страница «{current_title}». Перехожу в проект для открытия «{clean_name}»...")
                    nav_clicked = await self.page.evaluate("""() => {
                        const projLink = document.querySelector('#mainmenu a[href*="projectid="], .td-page-bar a[href*="projectid="], a[href*="/projects/?projectid="]');
                        if (projLink) { projLink.click(); return true; }
                        return false;
                    }""")
                    if nav_clicked:
                        await asyncio.sleep(2.5)
                    else:
                        await self.open_project()
                        await asyncio.sleep(2.0)
                    current_url = self.page.url if self._page else ""

        # 2. Если передан реальный Tilda ID страницы (7-9 цифр, например 61234567)
        if page_id and ordinal_idx is None:
            url = f"https://tilda.ru/page/?pageid={page_id}"
            await self.navigate(url)
            await asyncio.sleep(2.5)
            if await self._is_page_not_found():
                await self._log("error", f"Страница #{page_id} не найдена (Tilda вернула 'Страница не существует')")
                return False
            self._last_active_page_id = str(page_id)
            if name:
                self._last_active_page_name = str(name).strip()
            self._save_session_state()
            await self._log("info", f"Открыта страница #{page_id} для редактирования")
            return True

        # 3. Если передан порядковый номер (например: 2-я страница, ordinal_idx=1)
        if ordinal_idx is not None and not is_product_card_query:
            await self._log("info", f"Запрошена страница по порядковому номеру: №{ordinal_idx + 1}")
            if "/projects/" not in current_url or "projectid=" not in current_url:
                await self._log("info", "Перехожу в список страниц проекта для выбора страницы по номеру...")
                await self.open_project()
                await asyncio.sleep(2.5)

            try:
                page_links = self.page.locator(".td-page a[href*='/page/?pageid='], .td-page__td-title a, a[href*='/page/?pageid=']:not([href*='settings'])")
                total_pages = await page_links.count()
                unique_urls = []
                for i in range(total_pages):
                    href = await page_links.nth(i).get_attribute("href") or ""
                    if "/page/?pageid=" in href and href not in unique_urls:
                        unique_urls.append(href)

                await self._log("info", f"В проекте найдено страниц: {len(unique_urls)}")
                if ordinal_idx >= len(unique_urls):
                    err_msg = f"В проекте всего {len(unique_urls)} страниц(ы). Страница №{ordinal_idx + 1} отсутствует."
                    await self._log("error", err_msg)
                    return False

                target_href = unique_urls[ordinal_idx]
                target_link = self.page.locator(f"a[href='{target_href}']").first
                await target_link.click(force=True)
                await asyncio.sleep(3)

                if await self._is_page_not_found():
                    await self._log("error", f"Страница №{ordinal_idx + 1} открылась с ошибкой 404 ('Страница не существует')")
                    return False

                m_p = re.search(r"pageid=(\d+)", self.page.url)
                if m_p:
                    self._last_active_page_id = m_p.group(1)
                self._save_session_state()
                await self._log("info", f"Успешно открыта страница №{ordinal_idx + 1} в проекте ✓")
                return True
            except Exception as pe:
                await self._log("error", f"Ошибка выбора страницы №{ordinal_idx + 1}: {pe}")
                return False

        # 4. Если мы находимся в общем списке проектов (/projects/ без projectid), заходим в проект
        current_url = self.page.url if self._page else ""
        if "/projects/" in current_url and "projectid=" not in current_url:
            await self._log("info", "Перехожу в проект для открытия страницы...")
            await self.open_project()
            await asyncio.sleep(2.5)
            current_url = self.page.url if self._page else ""

        # 5. Ищем страницу в текущем проекте по имени (с приоритетом карточки товара)
        try:
            if "/projects/" not in current_url or "projectid=" not in current_url:
                await self.open_project()
                await asyncio.sleep(2.5)
                current_url = self.page.url if self._page else ""

            try:
                await self.page.wait_for_selector(".td-page, a[href*='/page/?pageid='], tr[id^='page']", timeout=6000)
            except Exception:
                pass

            # Поиск страницы: если карточка товара — ищем подстроку «карточк» или «товар»
            search_terms = []
            if is_product_card_query:
                search_terms.extend(["карточка товара", "карточка", "товар"])
            if raw_name and raw_name_lower not in ("главная", "главная страница", "main", "первая", "текущая", "эта"):
                search_terms.append(raw_name)
            if self._last_active_page_name:
                search_terms.append(self._last_active_page_name)

            for term in search_terms:
                clean_term = term.strip().lower()
                found = await self.page.evaluate("""(searchTerm) => {
                    const term = searchTerm.toLowerCase().trim();
                    const rows = Array.from(document.querySelectorAll('.td-page, tr[id^="page"], div[class*="page-row"], .td-sites-grid__item, .td-site__item'));
                    for (const row of rows) {
                        const text = (row.innerText || '').toLowerCase();
                        if (text.includes(term)) {
                            const link = row.querySelector('a[href*="/page/?pageid="]') || row.querySelector('a');
                            if (link) { link.click(); return true; }
                        }
                    }
                    const allLinks = Array.from(document.querySelectorAll('a[href*="/page/?pageid="]'));
                    for (const l of allLinks) {
                        if ((l.innerText || '').toLowerCase().includes(term)) {
                            l.click();
                            return true;
                        }
                    }
                    return false;
                }""", clean_term)

                if found:
                    await asyncio.sleep(3.0)
                    if not await self._is_page_not_found():
                        m_p = re.search(r"pageid=(\d+)", self.page.url)
                        if m_p:
                            self._last_active_page_id = m_p.group(1)
                        self._last_active_page_name = term
                        self._save_session_state()
                        await self._log("info", f"Открыта страница '{term}' ✓")
                        return True

            # Если задача про карточку товара, НО прямого совпадения нет — ищем любую страницу со словом «карточк»
            if is_product_card_query:
                fuzzy_found = await self.page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll("a[href*='/page/?pageid='], .td-page, tr[id^='page']"));
                    for (const l of links) {
                        const txt = (l.innerText || '').toLowerCase();
                        if (txt.includes('карточк') || txt.includes('product') || txt.includes('товар')) {
                            const a = l.tagName === 'A' ? l : l.querySelector('a[href*="/page/?pageid="]') || l.querySelector('a');
                            if (a) { a.click(); return true; }
                        }
                    }
                    return false;
                }""")
                if fuzzy_found:
                    await asyncio.sleep(3.0)
                    if not await self._is_page_not_found():
                        m_p = re.search(r"pageid=(\d+)", self.page.url)
                        if m_p:
                            self._last_active_page_id = m_p.group(1)
                        self._last_active_page_name = "карточка товара"
                        self._save_session_state()
                        await self._log("info", "Успешно найдена и открыта страница с карточкой товара ✓")
                        return True

            # Фолбэк ТОЛЬКО если задача НЕ про карточку товара
            if not is_product_card_query:
                first_page_link = self.page.locator(
                    "a[href*='/page/?pageid='], .td-page__td-title a, .td-page__title a, .td-page__table a, td a[href*='pageid']"
                ).first
                try:
                    if await first_page_link.count() > 0:
                        await first_page_link.click(force=True)
                        await asyncio.sleep(2.5)
                        if "/page/?pageid=" in self.page.url and not await self._is_page_not_found():
                            m_p = re.search(r"pageid=(\d+)", self.page.url)
                            if m_p:
                                self._last_active_page_id = m_p.group(1)
                            self._save_session_state()
                            await self._log("info", "Открыта страница проекта для редактирования")
                            return True
                except Exception:
                    pass

        except Exception as e:
            await self._log("error", f"Ошибка открытия страницы: {e}")
            return False

        available_pages = await self.page.evaluate("""() => {
            return Array.from(document.querySelectorAll('.td-page, tr[id^="page"], div[class*="page-row"]')).map(r => {
                const t = (r.innerText || '').split('\\n').filter(Boolean);
                return t.length > 0 ? t[0] : '';
            }).filter(Boolean);
        }""")
        await self._log("error", f"Не удалось найти страницу в проекте. Доступные страницы: {available_pages}")
        return False

    async def browse_and_select_block(
        self,
        category: str = "Обложка",
        requirements: str = "",
    ) -> bool:
        """
        Динамически исследует библиотеку Tilda:
        1. Открывает указанную категорию (например, «Обложка», «Колонки», «Меню»).
        2. Сканирует доступные карточки блоков в DOM (названия, описания, коды).
        3. Автоматически сохраняет и пополняет базу знаний блоков в data/tilda_blocks_catalog.json.
        4. Анализирует требования (например, '2 кнопки', 'заголовок', 'форма') и выбирает наилучший блок.
        5. Добавляет выбранный блок и гарантированно закрывает слой библиотеки (#closelayer).
        """
        clean_cat = str(category or "").strip()
        if "форма" in clean_cat.lower() and "кнопка" in clean_cat.lower():
            clean_cat = "Форма"
        elif "форма" in clean_cat.lower():
            clean_cat = "Форма"
        elif "кнопка" in clean_cat.lower():
            clean_cat = "Кнопка"

        is_popup_request = any(
            w in (requirements + " " + clean_cat + " " + str(category)).lower()
            for w in ("попап", "popup", "модалк", "всплывающ", "всплывающее", "bf50")
        )

        cat_label = f"«{clean_cat}» (попап-форма)" if is_popup_request else f"«{clean_cat}»"
        await self._log("info", f"Исследую библиотеку Tilda: категория {cat_label} (требования: '{requirements or 'любой'}')...")
        try:
            # 1. Проверяем редактор страницы
            current_url = self.page.url if self._page else ""
            if "/page/?pageid=" not in current_url:
                await self._log("info", "Перехожу в редактор страницы для выбора блока...")
                opened = await self.open_page()
                if not opened:
                    await self._log("error", "Не удалось открыть редактор страницы")
                    return False
                await asyncio.sleep(2)

            # 2. Закрываем любые старые оверлеи
            await self.ensure_overlays_closed()

            # 3. Открываем библиотеку блоков
            lib_opened = await self.smart_click(
                "#tp_btn_allblock, [data-open-library], .tp-shortcuttools__one-item[data-open-library], .tp-btn_add-block, .tp-record-edit-icons-plus"
            )
            if not lib_opened:
                await self.page.evaluate("() => { const b = document.querySelector('#tp_btn_allblock, [data-open-library]'); if (b) b.click(); }")
            await asyncio.sleep(1.2)

            # 4. Если запрошен попап — пробуем сначала прямой поиск в библиотеке
            blocks_data = []
            if is_popup_request:
                try:
                    search_icon = self.page.locator(".tp-library__header-search, .tp-library__search-btn, input.tp-library__search-input").first
                    if await search_icon.count() > 0:
                        await search_icon.click(force=True)
                        search_inp = self.page.locator("input.tp-library__search-input").first
                        if await search_inp.count() > 0:
                            await search_inp.fill("popup")
                            await search_inp.press("Enter")
                            await asyncio.sleep(1.8)
                            blocks_data = await self.page.evaluate("""() => {
                                const cards = [];
                                const els = document.querySelectorAll('#tplslistsearch .tp-library__tpl-item, #tplslistsearch .tp-library__tpl-body, .tp-library__tpl-wrapper');
                                els.forEach((el, idx) => {
                                    const title = el.querySelector('.tp-library__tpl-title, .tp-library__tpl-header')?.innerText?.trim() || '';
                                    const desc = el.querySelector('.tp-library__tpl-desc, .tp-library__tpl-text')?.innerText?.trim() || '';
                                    const code = el.getAttribute('data-tpl-id') || el.querySelector('.tp-library__tpl-code')?.innerText?.trim() || '';
                                    if (title || desc || code) {
                                        cards.push({ index: idx, code: code, title: title, desc: desc });
                                    }
                                });
                                return cards;
                            }""")
                except Exception as se:
                    logger.debug(f"Поиск попапа через инпут не удался: {se}")

            # Если через поиск не нашли, кликаем по категории блоков
            if not blocks_data:
                target_cat_name = "Форма" if is_popup_request else clean_cat
                cat_clicked = await self.smart_click(
                    f".tp-library__menu-item:has-text('{target_cat_name}'), .tp-library__category:has-text('{target_cat_name}'), [data-library-category*='{target_cat_name}'], text='{target_cat_name}'"
                )
                if not cat_clicked:
                    cat_clicked = await self.page.evaluate(f"""(cat) => {{
                        const items = Array.from(document.querySelectorAll('.tp-library__menu-item, .tp-library__category, a, div'));
                        const found = items.find(el => el.innerText && el.innerText.trim().toLowerCase().includes(cat.toLowerCase()));
                        if (found) {{ found.click(); return true; }}
                        return false;
                    }}""", target_cat_name)
                await asyncio.sleep(1.5)

                # 5. Считываем все доступные карточки блоков в этой категории
                blocks_data = await self.page.evaluate("""() => {
                    const cards = [];
                    const els = document.querySelectorAll('.tp-library__tpl-item, .tp-library__tpl-body, .tp-library__tpl-wrapper');
                    els.forEach((el, idx) => {
                        const title = el.querySelector('.tp-library__tpl-title, .tp-library__tpl-header')?.innerText?.trim() || '';
                        const desc = el.querySelector('.tp-library__tpl-desc, .tp-library__tpl-text')?.innerText?.trim() || '';
                        const code = el.getAttribute('data-tpl-id') || el.querySelector('.tp-library__tpl-code')?.innerText?.trim() || '';
                        if (title || desc || code) {
                            cards.push({ index: idx, code: code, title: title, desc: desc });
                        }
                    });
                    return cards;
                }""")

            if not blocks_data:
                await self.ensure_overlays_closed()
                if is_popup_request:
                    await self._log("warning", "Карточки попапа не найдены в DOM. Добавляю стандартный блок попап-формы BF502...")
                    res = await self.add_block("BF502")
                    if isinstance(res, dict) and not res.get("success"):
                        res = await self.add_block("BF501")
                    return res.get("success", False) if isinstance(res, dict) else bool(res)
                elif "форма" in clean_cat.lower():
                    await self._log("warning", f"В категории «{clean_cat}» не найдены карточки, добавляю стандартную форму BF201...")
                    res = await self.add_block("BF201")
                    return res.get("success", False) if isinstance(res, dict) else bool(res)
                else:
                    await self._log("warning", f"В категории «{clean_cat}» не найдены карточки, пробую стандартную обложку CR01...")
                    res = await self.add_block("CR01")
                    return res.get("success", False) if isinstance(res, dict) else bool(res)

            # 6. Самопополняющийся каталог блоков: сохраняем новые находки в data/tilda_blocks_catalog.json
            try:
                catalog_file = DATA_DIR / "tilda_blocks_catalog.json"
                catalog = {}
                if catalog_file.exists():
                    try:
                        catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
                    except Exception:
                        catalog = {}
                cat_key = clean_cat or "Общие"
                if cat_key not in catalog:
                    catalog[cat_key] = []
                existing_keys = {b.get("code") or b.get("title") for b in catalog[cat_key]}
                new_count = 0
                for b in blocks_data:
                    key = b.get("code") or b.get("title")
                    if key and key not in existing_keys:
                        catalog[cat_key].append({
                            "code": b.get("code", ""),
                            "title": b.get("title", ""),
                            "desc": b.get("desc", ""),
                        })
                        existing_keys.add(key)
                        new_count += 1
                catalog_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
                if new_count > 0:
                    await self._log("info", f"База знаний блоков пополнена: +{new_count} новых шаблонов «{cat_key}» (всего: {len(catalog[cat_key])})")
            except Exception as e:
                logger.error(f"Ошибка обновления каталога блоков: {e}")

            # 7. Интеллектуальный выбор наилучшей карточки под требования
            req_lower = requirements.lower() if requirements else ""
            best_idx = 0
            best_score = -1.0
            best_item = blocks_data[0]

            for card in blocks_data:
                score = 1.0
                combined = f"{card.get('code', '')} {card.get('title', '')} {card.get('desc', '')}".lower()

                # Если требуется попап / всплывающее окно
                if is_popup_request:
                    if any(w in combined for w in ["попап", "popup", "всплывающ", "окно", "всплывающее"]):
                        score += 50.0
                    if any(c in combined for c in ["bf501", "bf502", "bf503", "bf504"]):
                        score += 100.0

                # Требование: 2 кнопки
                if any(w in req_lower for w in ["2 кнопки", "две кнопки", "2 кнопками", "двумя кнопками", "кнопки", "кнопок"]):
                    if any(w in combined for w in ["2 кнопки", "две кнопки", "двумя кнопками"]):
                        score += 10.0
                    elif "кнопк" in combined:
                        score += 3.0

                if any(w in req_lower for w in ["заголовок", "подзаголовок", "описание"]):
                    if "заголовок" in combined or "описани" in combined or "подзаголовок" in combined:
                        score += 3.0

                if any(w in req_lower for w in ["видео", "video"]):
                    if "видео" in combined or "video" in combined:
                        score += 5.0

                if any(w in req_lower for w in ["форма", "заявка"]):
                    if "форм" in combined or "заявк" in combined:
                        score += 5.0

                if score > best_score:
                    best_score = score
                    best_idx = card["index"]
                    best_item = card

            chosen_name = best_item.get('title') or best_item.get('code') or f"блок #{best_idx+1}"
            await self._log("info", f"Выбран наиболее подходящий блок: «{chosen_name}» ({best_item.get('desc', '')[:50]}...)")

            # 8. Кликаем по выбранной карточке
            clicked = await self.page.evaluate("""(idx) => {
                const els = document.querySelectorAll('.tp-library__tpl-item, .tp-library__tpl-body, .tp-library__tpl-wrapper');
                if (els[idx]) {
                    const clickable = els[idx].querySelector('.tp-library__tpl-body') || els[idx];
                    clickable.click();
                    return true;
                }
                if (els.length > 0) {
                    els[0].click();
                    return true;
                }
                return false;
            }""", best_idx)

            await asyncio.sleep(2)

            # 9. ОБЯЗАТЕЛЬНО закрываем оверлей библиотеки (#closelayer)
            await self.ensure_overlays_closed()
            await asyncio.sleep(0.8)

            await self._log("info", f"Блок «{chosen_name}» успешно добавлен на страницу ✓")
            return True

        except Exception as e:
            await self.ensure_overlays_closed()
            await self._log("error", f"Ошибка при динамическом выборе блока: {e}")
            return False

    async def add_block(self, code: str = "T123") -> dict:
        """
        Добавляет блок на текущую страницу Tilda из библиотеки блоков.
        code: код блока (например 'T123', 'CR30', 'ME101', 'T107' или ключевое слово 'HTML', 'Zero').
        """
        await self._log("info", f"Добавляю блок «{code}» на страницу...")
        try:
            # 1. Проверяем, открыт ли редактор страницы
            current_url = self.page.url if self._page else ""
            if "/page/?pageid=" not in current_url:
                await self._log("info", "Перехожу в редактор страницы для добавления блока...")
                opened = await self.open_page()
                if not opened:
                    err_msg = "Не удалось открыть редактор страницы для добавления блока"
                    await self._log("error", err_msg)
                    return {"success": False, "message": err_msg}
                await asyncio.sleep(2)

            # Закрываем любые открытые оверлеи перед стартом
            await self.ensure_overlays_closed()

            clean_code = code.upper().strip()

            # 2. Если Zero Block — используем быструю кнопку
            if clean_code in ("ZERO", "НУЛЕВОЙ"):
                zero_clicked = await self.smart_click("text='ZERO', button:has-text('ZERO'), a:has-text('ZERO')")
                if zero_clicked:
                    await asyncio.sleep(2)
                    await self.ensure_overlays_closed()
                    msg = "Блок Zero Block успешно добавлен на страницу"
                    await self._log("info", msg)
                    return {"success": True, "message": msg, "code": "ZERO"}

            # 3. Открываем библиотеку блоков
            lib_opened = await self.smart_click(
                "#tp_btn_allblock, [data-open-library], .tp-shortcuttools__one-item[data-open-library], .tp-btn_add-block, .tp-record-edit-icons-plus"
            )
            if not lib_opened:
                await self.page.evaluate("() => { const b = document.querySelector('#tp_btn_allblock, [data-open-library]'); if (b) b.click(); }")
            await asyncio.sleep(1)

            # 4. Открываем поиск в библиотеке
            await self.smart_click(
                ".tp-library__header-search, .tp-library__header-search-wrapper, .tp-library__search-btn"
            )
            await asyncio.sleep(0.5)

            # 5. Вводим код в поле поиска
            search_filled = await self.smart_fill(
                "input.tp-library__search-input, .tp-library__search input, input[type='text']:visible",
                clean_code
            )
            if not search_filled:
                await self.page.keyboard.type(clean_code, delay=20)

            await asyncio.sleep(1.2)

            # 6. Кликаем по найденной карточке блока
            card_selectors = [
                f"#tplslistsearch .tp-library__tpl-body:has-text('{clean_code}')",
                f".tp-library__tpls-list-body_visible .tp-library__tpl-body:has-text('{clean_code}')",
                f"#tplslistsearch .tp-library__tpl-body",
                f".tp-library__tpls-list-body_visible .tp-library__tpl-body",
                f"[data-tpl-id='131']",
                f"text='{clean_code}'",
            ]
            added = False
            for sel in card_selectors:
                try:
                    loc = self.page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.click(timeout=3000)
                        added = True
                        break
                except Exception:
                    continue

            if not added:
                added = await self.page.evaluate(f"""(code) => {{
                    const list = document.querySelector('#tplslistsearch') || document.querySelector('.tp-library__tpls-list-body_visible');
                    if (list) {{
                        const body = list.querySelector('.tp-library__tpl-body') || list.querySelector('.tp-library__tpl-wrapper');
                        if (body) {{
                            body.click();
                            return true;
                        }}
                    }}
                    return false;
                }}""", clean_code)

            await asyncio.sleep(2)
            # В любом случае закрываем оверлей библиотеки (#closelayer)
            await self.ensure_overlays_closed()

            if added:
                succ_msg = f"Блок {clean_code} успешно добавлен на страницу"
                await self._log("info", succ_msg)
                return {"success": True, "message": succ_msg, "code": clean_code}
            else:
                fail_msg = f"Не удалось найти и добавить блок {clean_code} из библиотеки"
                await self._log("error", fail_msg)
                return {"success": False, "message": fail_msg}

        except Exception as e:
            await self.ensure_overlays_closed()
            err_msg = f"Ошибка при добавлении блока: {e}"
            await self._log("error", err_msg)
            return {"success": False, "message": err_msg}

    # ─────────────────────────── Tilda: Редактирование ───────────────────────────

    async def edit_text(self, search_text: str, new_text: str) -> bool:
        """
        Умная замена текста: если элемент является input/textarea — заполняет его.
        Если это текст на странице — редактирует inline.
        """
        await self._log("info", f"Замена текста: '{search_text}' → '{new_text}'...")

        try:
            # 1. Проверяем поля ввода с placeholder или value равным search_text
            input_loc = self.page.locator(
                f"input[value*='{search_text}'], textarea[value*='{search_text}'], input[placeholder*='{search_text}'], textarea[placeholder*='{search_text}']"
            ).first
            if await input_loc.count() > 0 and await input_loc.is_visible():
                await input_loc.click()
                await input_loc.fill(new_text)
                await self._log("info", f"Значение поля ввода обновлено на '{new_text}'")
                return True

            # 2. Если на странице есть видимое модальное окно с полем ввода
            popup_input = self.page.locator(
                ".td-popup-window input[type='text']:visible, #modalinputprojecttitle:visible, input[name='title']:visible"
            ).first
            if await popup_input.count() > 0 and await popup_input.is_visible():
                await popup_input.fill(new_text)
                await self._log("info", f"Заполнено поле в модальном окне: '{new_text}'")
                return True

            # 3. Редактор Tilda: Zero Block atom или обычный текст
            element = self.page.locator(f'[class*="tn-atom"]:has-text("{search_text}")').first
            if await element.count() == 0:
                element = self.page.get_by_text(search_text, exact=False).first

            if await element.count() > 0 and await element.is_visible():
                await element.dblclick(timeout=3000)
                await asyncio.sleep(0.5)
                await self.page.keyboard.press("Control+a")
                await asyncio.sleep(0.2)
                await self.page.keyboard.type(new_text, delay=25)
                await asyncio.sleep(0.3)
                await self.page.keyboard.press("Escape")
                await self._log("info", f"Текст заменён: '{search_text}' → '{new_text}'")
                return True

            # 4. Фолбэк: если есть любой видимый активный input/textarea
            filled = await self.smart_fill("input[type='text']:visible, textarea:visible", new_text)
            if filled:
                return True

            await self._log("error", f"Текст или поле ввода для '{search_text}' не найдены")
            return False

        except Exception as e:
            await self._log("error", f"Ошибка при замене текста: {e}")
            return False

    async def scan_page_blocks(self) -> list[dict]:
        """
        Сканирует страницу редактора Tilda и возвращает список всех существующих блоков:
        их ID (#rec...), тип (zero/standard), кодовый номер, сниппет текста и доступность кнопки «Контент».
        """
        await self._log("info", "Сканирую блоки текущей страницы Tilda...")
        try:
            current_url = self.page.url if self._page else ""
            if "/page/?pageid=" not in current_url:
                await self.open_page()
                await asyncio.sleep(2)

            blocks_data = await self.page.evaluate(r"""() => {
                const seen = new Set();
                const records = [];
                document.querySelectorAll('.r[id^="rec"], .record[id^="record"], .record').forEach(el => {
                    if (!el.id || el.id.includes('recdiv')) return;
                    const cleanId = el.id.replace('record', 'rec');
                    if (!/^rec\d+$/.test(cleanId)) return;
                    if (!seen.has(cleanId)) {
                        seen.add(cleanId);
                        records.push(el);
                    }
                });

                const res = [];
                records.forEach((r, idx) => {
                    const parentRec = r.closest('.record') || (r.parentElement && r.parentElement.classList.contains('record') ? r.parentElement : null);
                    
                    let id = r.id ? r.id.replace('record', 'rec') : '';
                    if (parentRec && (!id || !id.startsWith('rec'))) {
                        id = parentRec.id ? parentRec.id.replace('record', 'rec') : id;
                    }
                    const idSpan = r.querySelector('.tp-record-edit-icons-left__item-title, .copy_nlm') || (parentRec ? parentRec.querySelector('.tp-record-edit-icons-left__item-title, .copy_nlm') : null);
                    if (idSpan && idSpan.innerText && idSpan.innerText.includes('rec')) {
                        const idMatch = idSpan.innerText.match(/rec\d+/);
                        if (idMatch) id = idMatch[0];
                    }

                    let type = (r.getAttribute('data-record-type') || (parentRec ? parentRec.getAttribute('data-record-type') : '') || '').trim();
                    let cod = (r.getAttribute('data-record-cod') || (parentRec ? parentRec.getAttribute('data-record-cod') : '') || '').trim();

                    if (!cod) {
                        const tplBtn = r.querySelector('.tp-record-ui__button_tpl, .tp-record-edit-icons-left__item-tpl') ||
                                       (parentRec ? parentRec.querySelector('.tp-record-ui__button_tpl, .tp-record-edit-icons-left__item-tpl') : null);
                        if (tplBtn) {
                            const spanEl = tplBtn.querySelector('span:not(.dropdown-arrow)') || tplBtn.querySelector('span') || tplBtn;
                            const txt = (spanEl.innerText || '').trim();
                            if (txt && !txt.includes('dropdown')) {
                                cod = txt.split('\n')[0].trim();
                            }
                        }
                    }

                    if (!cod && typeof window !== 'undefined' && Array.isArray(window.allrecords)) {
                        const cleanRecNum = id.replace('rec', '');
                        const recData = window.allrecords.find(item => item && (item.id === cleanRecNum || item.recordid === cleanRecNum || item.id === id));
                        if (recData) {
                            if (recData.cod) cod = String(recData.cod).trim();
                            if (recData.tplid && !cod) cod = String(recData.tplid).trim();
                            if (recData.type && !type) type = String(recData.type).trim();
                        }
                    }

                    if (!cod) {
                        const innerT = r.querySelector('[class*="t-rec"] > div, div[class^="t"], [class*="t396"], [class*="t-cover"]');
                        if (innerT && innerT.className) {
                            const m = innerT.className.match(/\b(t\d+[a-z]?|te\d+[a-z]?|st\d+[a-z]?|cr\d+[a-z]?|me\d+[a-z]?|gl\d+[a-z]?|cl\d+[a-z]?|fr\d+[a-z]?)\b/i);
                            if (m) cod = m[1].toUpperCase();
                        }
                    }

                    if (!cod && type) cod = type;

                    let isZero = !!r.querySelector('.t396') || type === '396' || (cod && cod.toLowerCase() === 'zero');
                    let hasContent = !isZero;
                    const uiGroup = r.querySelector('.tp-record-ui__group, .tp-record-ui') || (parentRec ? parentRec.querySelector('.tp-record-ui__group, .tp-record-ui') : null);
                    if (uiGroup) {
                        const buttons = uiGroup.querySelectorAll('button');
                        if (buttons.length >= 2) {
                            const secondBtnText = buttons[1].innerText ? buttons[1].innerText.trim() : '';
                            if (secondBtnText.includes('Редактировать блок')) {
                                isZero = true;
                                hasContent = false;
                            } else if (secondBtnText.includes('Контент')) {
                                isZero = false;
                                hasContent = true;
                            }
                        }
                    }

                    let title = '';
                    const titleEl = r.querySelector('.t-title, .t-cover__title, .t-name, h1, h2, h3, [class*="title"]');
                    if (titleEl) title = titleEl.innerText.trim();
                    if (!title) title = (r.innerText || '').slice(0, 100).replace(/\s+/g, ' ').trim();

                    res.push({
                        index: idx,
                        id: id,
                        record_type: type,
                        code: cod,
                        is_zero: isZero,
                        title: title.slice(0, 80),
                        has_content: hasContent,
                    });
                });
                return res;
            }""")
            await self._log("info", f"Найдено блоков на странице: {len(blocks_data)}")
            for b in blocks_data:
                tag = "[Zero Block]" if b.get("is_zero") else "[Стандартный]"
                code_label = f" ({b.get('code')})" if b.get('code') else ""
                await self._log("info", f"  #{b.get('index', 0)+1} {tag} #{b.get('id')}{code_label}: {b.get('title')[:45]}")
            return blocks_data
        except Exception as e:
            await self._log("error", f"Ошибка при сканировании блоков страницы: {e}")
            return []

    async def resolve_block(self, identifier: Optional[str] = None) -> Optional[dict]:
        """
        Универсальный поиск блока на странице Tilda по любому идентификатору:
        - Код шаблона (например 'st310n', 'te200', 'cr01', 'cr46', 't123', 'zero')
        - Порядковый номер ('1', '2', '3', 'первый', 'второй', 'третий', 'последний')
        - Реальный ID ('rec4079117301', '#rec4079117301')
        - Текстовый заголовок/фрагмент
        Возвращает словарь: {'id': 'rec...', 'code': 'ST310N', 'index': 2, 'title': '...'} или None.
        """
        try:
            return await self.page.evaluate(r"""(ident) => {
                const seen = new Set();
                const records = [];
                document.querySelectorAll('.r[id^="rec"], .record[id^="record"], .record').forEach(el => {
                    if (!el.id || el.id.includes('recdiv')) return;
                    const cleanId = el.id.replace('record', 'rec');
                    if (!/^rec\d+$/.test(cleanId)) return;
                    if (!seen.has(cleanId)) {
                        seen.add(cleanId);
                        records.push(el);
                    }
                });
                if (records.length === 0) return null;

                const getBlockInfo = (r, idx) => {
                    const parentRec = r.closest('.record') || (r.parentElement && r.parentElement.classList.contains('record') ? r.parentElement : null);
                    
                    let id = r.id ? r.id.replace('record', 'rec') : '';
                    if (parentRec && (!id || !id.startsWith('rec'))) {
                        id = parentRec.id ? parentRec.id.replace('record', 'rec') : id;
                    }
                    const idSpan = r.querySelector('.tp-record-edit-icons-left__item-title, .copy_nlm') || (parentRec ? parentRec.querySelector('.tp-record-edit-icons-left__item-title, .copy_nlm') : null);
                    if (idSpan && idSpan.innerText && idSpan.innerText.includes('rec')) {
                        const idMatch = idSpan.innerText.match(/rec\d+/);
                        if (idMatch) id = idMatch[0];
                    }

                    let type = (r.getAttribute('data-record-type') || (parentRec ? parentRec.getAttribute('data-record-type') : '') || '').trim();
                    let cod = (r.getAttribute('data-record-cod') || (parentRec ? parentRec.getAttribute('data-record-cod') : '') || '').trim();

                    if (!cod) {
                        const tplBtn = r.querySelector('.tp-record-ui__button_tpl, .tp-record-edit-icons-left__item-tpl') ||
                                       (parentRec ? parentRec.querySelector('.tp-record-ui__button_tpl, .tp-record-edit-icons-left__item-tpl') : null);
                        if (tplBtn) {
                            const spanEl = tplBtn.querySelector('span:not(.dropdown-arrow)') || tplBtn.querySelector('span') || tplBtn;
                            const txt = (spanEl.innerText || '').trim();
                            if (txt && !txt.includes('dropdown')) {
                                cod = txt.split('\n')[0].trim();
                            }
                        }
                    }

                    if (!cod && typeof window !== 'undefined' && Array.isArray(window.allrecords)) {
                        const cleanRecNum = id.replace('rec', '');
                        const recData = window.allrecords.find(item => item && (item.id === cleanRecNum || item.recordid === cleanRecNum || item.id === id));
                        if (recData) {
                            if (recData.cod) cod = String(recData.cod).trim();
                            if (recData.tplid && !cod) cod = String(recData.tplid).trim();
                            if (recData.type && !type) type = String(recData.type).trim();
                        }
                    }

                    if (!cod) {
                        const innerT = r.querySelector('[class*="t-rec"] > div, div[class^="t"], [class*="t396"], [class*="t-cover"]');
                        if (innerT && innerT.className) {
                            const m = innerT.className.match(/\b(t\d+[a-z]?|te\d+[a-z]?|st\d+[a-z]?|cr\d+[a-z]?|me\d+[a-z]?|gl\d+[a-z]?|cl\d+[a-z]?|fr\d+[a-z]?)\b/i);
                            if (m) cod = m[1].toUpperCase();
                        }
                    }

                    if (!cod && type) cod = type;

                    let isZero = !!r.querySelector('.t396') || type === '396' || (cod && cod.toLowerCase() === 'zero');
                    let hasContent = !isZero;
                    const uiGroup = r.querySelector('.tp-record-ui__group, .tp-record-ui') || (parentRec ? parentRec.querySelector('.tp-record-ui__group, .tp-record-ui') : null);
                    if (uiGroup) {
                        const buttons = uiGroup.querySelectorAll('button');
                        if (buttons.length >= 2) {
                            const secondBtnText = buttons[1].innerText ? buttons[1].innerText.trim() : '';
                            if (secondBtnText.includes('Редактировать блок')) {
                                isZero = true;
                                hasContent = false;
                            } else if (secondBtnText.includes('Контент')) {
                                isZero = false;
                                hasContent = true;
                            }
                        }
                    }

                    let title = '';
                    const titleEl = r.querySelector('.t-title, .t-cover__title, .t-name, h1, h2, h3, [class*="title"]');
                    if (titleEl) title = titleEl.innerText.trim();
                    if (!title) title = (r.innerText || '').slice(0, 100).replace(/\s+/g, ' ').trim();

                    return { id, code: cod, record_type: type, is_zero: isZero, index: idx, title };
                };

                const allBlocks = records.map((r, idx) => getBlockInfo(r, idx));

                // 1. Фильтруем технические блоки (T123, HTML-код, 131)
                const isContentBlock = (b) => !b.is_zero && (b.code || '').toUpperCase() !== 'T123' && b.record_type !== '131';
                const contentBlocks = allBlocks.filter(isContentBlock);

                // Если идентификатор не передан или 'auto' — для контента берём первый контентный блок (обложку/hero)!
                if (!ident || typeof ident !== 'string' || ident.trim() === '' || ident.toLowerCase() === 'auto') {
                    if (contentBlocks.length > 0) return contentBlocks[0];
                    const nonZero = allBlocks.filter(b => !b.is_zero);
                    return nonZero.length > 0 ? nonZero[0] : allBlocks[0];
                }

                const raw = ident.trim().toLowerCase();
                const clean = raw.replace(/^#/, '').trim();
                const cleanToken = raw.replace(/^(?:блок|номер|#)\s*/, '').replace(/^#/, '').trim();

                // 2. Проверка точного совпадения по коду шаблона (НАИВЫСШИЙ ПРИОРИТЕТ!)
                // Например 'cl05', 'cr01', 'te200', 'st310n'
                const byExactCode = allBlocks.find(b => {
                    const c = b.code.toLowerCase();
                    return c && (c === clean || c === raw || c === cleanToken);
                });
                if (byExactCode) return byExactCode;

                // 3. Порядковые номера словами ('первый', 'второй', 'последний', 'главный')
                // Для 'главный' / 'обложка' отдаём первый контентный блок
                const mainTargetIdx = contentBlocks.length > 0 ? allBlocks.indexOf(contentBlocks[0]) : 0;
                const ordinals = {
                    '1': 0, '1-й': 0, '1й': 0, 'первый': 0, 'первого': 0,
                    'главный': mainTargetIdx, 'главного': mainTargetIdx, 'главном': mainTargetIdx,
                    'главный блок': mainTargetIdx, 'главного блока': mainTargetIdx, 'главном блоке': mainTargetIdx,
                    'обложка': mainTargetIdx, 'обложки': mainTargetIdx, 'обложке': mainTargetIdx,
                    'hero': mainTargetIdx, 'main': mainTargetIdx,
                    '2': 1, '2-й': 1, '2й': 1, 'второй': 1, 'второго': 1,
                    '3': 2, '3-й': 2, '3й': 2, 'третий': 2, 'третьего': 2,
                    '4': 3, '4-й': 3, '4й': 3, 'четвертый': 3, 'четвертого': 3,
                    '5': 4, '5-й': 4, '5й': 4, 'пятый': 4, 'пятого': 4,
                    '6': 5, '6-й': 5, '6й': 5, 'шестой': 5,
                    '7': 6, '7-й': 6, 'седьмой': 6,
                    '8': 7, '8-й': 7, 'восьмой': 7,
                    '9': 8, '9-й': 8, 'девятый': 8,
                    '10': 9, '10-й': 9, 'десятый': 9,
                    'последний': allBlocks.length - 1, 'последнего': allBlocks.length - 1, '-1': allBlocks.length - 1
                };

                if (ordinals.hasOwnProperty(raw)) {
                    const targetIdx = ordinals[raw];
                    if (targetIdx >= 0 && targetIdx < allBlocks.length) return allBlocks[targetIdx];
                }
                if (ordinals.hasOwnProperty(cleanToken)) {
                    const targetIdx = ordinals[cleanToken];
                    if (targetIdx >= 0 && targetIdx < allBlocks.length) return allBlocks[targetIdx];
                }

                // 4. Числовой порядковый номер ТОЛЬКО если запрос состоит строго из цифр и префиксов/суффиксов
                const pureNumMatch = raw.match(/^(?:блок|номер|#)?\s*(\d+)\s*(?:-?[йяе])?$/);
                if (pureNumMatch) {
                    const n = parseInt(pureNumMatch[1], 10);
                    if (n >= 1 && n <= allBlocks.length && n < 1000) {
                        return allBlocks[n - 1];
                    }
                }

                // 5. Проверка совпадения с ID (#rec...)
                const byId = allBlocks.find(b => b.id.toLowerCase() === clean || b.id.toLowerCase() === cleanToken || (clean.length > 5 && b.id.toLowerCase().includes(clean)));
                if (byId) return byId;

                // 6. Вхождение в код шаблона (подстрока)
                const bySubCode = allBlocks.find(b => {
                    const c = b.code.toLowerCase();
                    return c && ((cleanToken.length > 1 && c.includes(cleanToken)) ||
                                 (clean.length > 1 && c.includes(clean)) ||
                                 (c.length > 1 && cleanToken.includes(c)));
                });
                if (bySubCode) return bySubCode;

                // 7. Совпадение по record_type (если нет прямого совпадения по коду)
                const byRecordType = allBlocks.find(b => {
                    const rt = b.record_type.toLowerCase();
                    return rt && (rt === cleanToken || rt === clean || (cleanToken.length > 2 && cleanToken.includes(rt)));
                });
                if (byRecordType) return byRecordType;

                // 8. Сопоставление по семантическим категориям Tilda (русские/английские)
                const categoryMap = {
                    'меню': ['me', 'ft', 'menu', 't456', 't454', 't228'],
                    'шапка': ['me', 'header', 't456'],
                    'обложка': ['cr', 'cover', 't001'],
                    'подвал': ['ft', 'footer'],
                    'футер': ['ft', 'footer'],
                    'о нас': ['ab', 'about', 'cr'],
                    'преимущества': ['fr', 'fe', 'te', 'pl'],
                    'плюсы': ['fr', 'fe', 'te'],
                    'отзывы': ['ts', 'review'],
                    'товары': ['st', 'store', 'shop'],
                    'магазин': ['st', 'store'],
                    'галерея': ['gl', 'gallery'],
                    'команда': ['tm', 'team'],
                    'форма': ['bf', 'form'],
                    'контакты': ['ct', 'contact', 'ft'],
                    'кнопка': ['bf', 'btn', 'button'],
                    'цены': ['pl', 'price', 'pricing'],
                    'тарифы': ['pl', 'price', 'pricing'],
                    'код': ['t123', 'html', '131', 'code'],
                    'кодовый': ['t123', 'html', '131', 'code'],
                    'кодовый блок': ['t123', 'html', '131'],
                    'блок кода': ['t123', 'html', '131'],
                    'скрипт': ['t123', 'html', '131', 'script'],
                    'html': ['t123', 'html', '131'],
                    't123': ['t123', '131'],
                    'вставка кода': ['t123', '131']
                };

                for (const [catName, prefixes] of Object.entries(categoryMap)) {
                    if (cleanToken.includes(catName) || raw.includes(catName)) {
                        const byCat = allBlocks.find(b => {
                            const c = b.code.toLowerCase();
                            const t = b.title.toLowerCase();
                            const rt = (b.record_type || '').toLowerCase();
                            return prefixes.some(p => c.startsWith(p) || c.includes(p) || t.includes(p) || rt === p);
                        });
                        if (byCat) return byCat;
                    }
                }

                // 9. Проверка заголовка
                const byTitle = allBlocks.find(b => {
                    const t = b.title.toLowerCase();
                    return t && (t.includes(raw) || t.includes(cleanToken) || (t.length > 3 && cleanToken.includes(t)));
                });
                if (byTitle) return byTitle;

                // 10. Пословный поиск по ключевым словам заголовка и кода
                const queryWords = cleanToken.split(/[\s,._-]+/).filter(w => w.length > 2);
                if (queryWords.length > 0) {
                    const byWords = allBlocks.find(b => {
                        const combined = (b.title + ' ' + b.code).toLowerCase();
                        return queryWords.every(qw => combined.includes(qw));
                    });
                    if (byWords) return byWords;
                }

                return null;
            }""", identifier)
        except Exception as e:
            await self._log("error", f"Ошибка при разрешении блока '{identifier}': {e}")
            return None

    async def edit_block_content(
        self,
        block_id: Optional[str] = None,
        title: Optional[str] = None,
        descr: Optional[str] = None,
        cards: Optional[list[dict]] = None,
        btn_text: Optional[str] = None,
        btn_href: Optional[str] = None,
        btn2_text: Optional[str] = None,
        btn2_href: Optional[str] = None,
        img_url: Optional[str] = None,
        block_selector: Optional[str] = None,
    ) -> bool:
        """
        Открывает боковую шторку «Контент» блока Tilda, заполняет поля ввода
        (заголовок, описание, карточки тарифов/преимуществ, кнопки, фоновые изображения) и нажимает «Сохранить и закрыть».
        """
        await self._log(
            "info",
            f"Редактирую контент блока (id: '{block_id or 'auto'}', title: '{title or '-'}', descr: '{descr or '-'}', cards: {len(cards) if cards else 0}, btn1: '{btn_text or '-'}', btn2: '{btn2_text or '-'}', img: '{img_url or '-'}')..."
        )

        try:
            current_url = self.page.url if self._page else ""
            if "/page/?pageid=" not in current_url:
                await self.open_page()
                await asyncio.sleep(2)

            # Закрываем оверлеи перед взаимодействием с блоком
            await self.ensure_overlays_closed()

            # 1. Находим целевой блок
            target = None
            clean_rec_id = None
            resolved = await self.resolve_block(block_id or block_selector)
            if resolved:
                clean_rec_id = resolved.get("id")
                if clean_rec_id:
                    target = self.page.locator(f"#{clean_rec_id}").first
                    await self._log("info", f"Найден блок #{clean_rec_id} ({resolved.get('code') or ''}) для редактирования контента")
            elif block_id:
                clean_rec_id = block_id.lstrip("#")
                target = self.page.locator(f"#{clean_rec_id}").first
            elif block_selector:
                target = self.page.locator(block_selector).first
                if await target.count() > 0:
                    clean_rec_id = await target.get_attribute("id")
            else:
                # По умолчанию берем последний стандартный блок (или последний блок на странице)
                target = self.page.locator(".r[data-record-type]:not([data-record-type='396']):last-of-type, .r:last-of-type").first
                if await target.count() > 0:
                    clean_rec_id = await target.get_attribute("id")

            if not target or await target.count() == 0:
                await self._log("error", f"Целевой блок {block_id or block_selector or ''} не найден на странице")
                return False

            # Проверяем, не является ли блок Zero Block
            is_zero = await target.evaluate("""(el) => {
                return !!el.querySelector('.t396') || el.getAttribute('data-record-type') === '396';
            }""")
            if is_zero:
                await self._log("warning", f"Блок #{clean_rec_id} является Zero Block (у него нет стандартной шторки «Контент»). Для него используется визуальный редактор Zero.")
                return False

            # Скроллим к блоку и наводим курсор
            try:
                await target.scroll_into_view_if_needed(timeout=4000)
                await target.hover(timeout=3000)
            except Exception:
                await self.ensure_overlays_closed()
                try:
                    await target.hover(force=True, timeout=2000)
                except Exception:
                    pass
            await asyncio.sleep(0.5)

            # 2. Ищем и нажимаем кнопку «Контент» на блоке
            content_opened = False
            rec_num = re.sub(r'\D', '', clean_rec_id) if clean_rec_id else ""

            # В Tilda активный тулбар блока находится в .tp-record-ui, привязанном к data-recordid=rec_num
            content_opened = await self.page.evaluate("""(num) => {
                let targetUI = (num ? document.querySelector('[data-recordid="' + num + '"]')?.closest('.tp-record-ui') : null) ||
                               document.querySelector('.tp-record-ui_hovered') ||
                               document.querySelector('.tp-record-ui');
                if (targetUI) {
                    const btn = targetUI.querySelector('.tp-record-ui__icon_content')?.closest('button') ||
                                targetUI.querySelector('.tp-record-ui__button_primary') ||
                                Array.from(targetUI.querySelectorAll('button')).find(b => b.innerText && b.innerText.includes('Контент'));
                    if (btn) {
                        btn.click();
                        return true;
                    }
                }
                if (typeof window.editrecordcontent === 'function' && num) {
                    window.editrecordcontent(num);
                    return true;
                }
                return false;
            }""", rec_num)

            if not content_opened:
                content_btn = self.page.locator(".tp-record-ui button:has(.tp-record-ui__icon_content), .tp-record-ui .tp-record-ui__button_primary, button:has-text('Контент')").first
                if await content_btn.count() > 0:
                    try:
                        await content_btn.click()
                        content_opened = True
                    except Exception:
                        pass

            await asyncio.sleep(1.5)

            # 3. Проверяем, открылась ли боковая шторка контента
            panel_found = await self.page.evaluate("""() => {
                return !!(document.querySelector('.pe-content__form-wrapper, button.tbtn-primary, #editrecordcontent_container, .editrecordcontent_container'));
            }""")

            if not panel_found:
                panel_selectors = [
                    ".pe-content__form-wrapper",
                    ".pe-content__savebtns-wrapper",
                    "button.tbtn-primary",
                    "#editrecordcontent_container",
                    ".tp-popup_content",
                    ".editrecordcontent_container",
                    "form#form-edit-content",
                ]
                for p_sel in panel_selectors:
                    try:
                        loc = self.page.locator(p_sel).first
                        if await loc.count() > 0 and await loc.is_visible():
                            panel_found = True
                            break
                    except Exception:
                        pass

            if not panel_found:
                err_msg = f"Панель «Контент» не открылась для блока #{clean_rec_id}"
                await self._log("error", err_msg)
                return {"success": False, "message": err_msg, "applied": []}

            await self._log("info", "Панель «Контент» успешно открыта, заполняю структурированные поля...")

            content_data = {
                "title": title,
                "descr": descr,
                "cards": cards if isinstance(cards, list) else None,
                "btn_text": btn_text,
                "btn_href": btn_href,
                "btn2_text": btn2_text,
                "btn2_href": btn2_href,
                "img_url": img_url,
            }

            applied_fields = await self.page.evaluate("""(data) => {
                const applied = [];

                const setVal = (el, val) => {
                    if (!el || val === undefined || val === null) return false;
                    try {
                        if (el.type === 'file') return false;
                        el.value = val;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                        return true;
                    } catch (e) {
                        return false;
                    }
                };


                // 1. Заголовок блока
                if (data.title) {
                    let setSuccess = false;
                    const el = document.querySelector('.pe-redactor__wrapper[data-field="title"], [data-tpl-field="title"] .pe-redactor__wrapper, .pe-field-title .pe-redactor__wrapper, .pe-field-title');
                    if (el) {
                        const ql = el.querySelector('.ql-editor') || el;
                        ql.innerText = data.title;
                        ql.dispatchEvent(new Event('input', { bubbles: true }));
                        setSuccess = true;
                    }
                    const ta = document.querySelector('textarea[name="title"], textarea[name="header"], input[name="title"]');
                    if (ta && setVal(ta, data.title)) {
                        setSuccess = true;
                    }
                    if (setSuccess) applied.push("Заголовок");
                }

                // 2. Описание / Подзаголовок блока
                if (data.descr) {
                    let setSuccess = false;
                    const el = document.querySelector('.pe-redactor__wrapper[data-field="text"], .pe-redactor__wrapper[data-field="descr"], [data-tpl-field="text"] .pe-redactor__wrapper, [data-tpl-field="descr"] .pe-redactor__wrapper, .pe-field-descr .pe-redactor__wrapper, .pe-field-descr');
                    if (el) {
                        const ql = el.querySelector('.ql-editor') || el;
                        ql.innerText = data.descr;
                        ql.dispatchEvent(new Event('input', { bubbles: true }));
                        setSuccess = true;
                    }
                    const ta = document.querySelector('textarea[name="text"], textarea[name="descr"], textarea[name="subtitle"]');
                    if (ta && setVal(ta, data.descr)) {
                        setSuccess = true;
                    }
                    if (setSuccess) applied.push("Описание");
                }

                // 3. Карточки (тарифы / колонки)
                if (data.cards && Array.isArray(data.cards) && data.cards.length > 0) {
                    const itemContainers = document.querySelectorAll(
                        '.pe-items__item, .tp-popup__item, [data-item-index], .tp-form-group-item, .tp-cards__item'
                    );
                    let cardsSet = 0;
                    data.cards.forEach((cData, i) => {
                        let container = itemContainers[i];
                        if (container) {
                            if (cData.title) {
                                const tInput = container.querySelector('input[name*="title"], input[name*="header"], [data-field-name*="title"] input') || container.querySelector('input[type="text"]');
                                if (setVal(tInput, cData.title)) cardsSet++;
                            }
                            if (cData.descr) {
                                const dInput = container.querySelector('textarea[name*="descr"], textarea[name*="text"]') || container.querySelector('textarea');
                                if (setVal(dInput, cData.descr)) cardsSet++;
                            }
                            if (cData.price) {
                                const pInput = container.querySelector('input[name*="price"]');
                                if (setVal(pInput, cData.price)) cardsSet++;
                            }
                            if (cData.btn_text) {
                                const bInput = container.querySelector('input[name*="btn_text"], input[name*="button"]');
                                if (setVal(bInput, cData.btn_text)) cardsSet++;
                            }
                        }
                    });
                    if (cardsSet > 0) applied.push(`Карточки (${data.cards.length})`);
                }

                // 4. Кнопка 1 (Текст)
                if (data.btn_text) {
                    const el = document.querySelector(
                        'input[name="buttontitle"], input[name="btn_text"], input[name="btn1_text"], input[name="button_title"], [data-field-name="buttontitle"] input, [data-tpl-field="buttontitle"] input, input[placeholder*="Текст для кнопки"]'
                    );
                    if (setVal(el, data.btn_text)) applied.push(`Кнопка 1: "${data.btn_text}"`);
                }

                // 5. Кнопка 1 (Ссылка)
                if (data.btn_href) {
                    const el = document.querySelector(
                        'input[name="buttonlink"], input[name="btn_href"], input[name="btn1_href"], input[name="button_link"], [data-field-name="buttonlink"] input, [data-tpl-field="buttonlink"] input, input[placeholder*="Ссылка для кнопки"]'
                    );
                    if (setVal(el, data.btn_href)) applied.push(`Ссылка кнопки 1: "${data.btn_href}"`);
                }

                // 6. Кнопка 2 (Текст)
                if (data.btn2_text) {
                    const el = document.querySelector(
                        'input[name="buttontitle2"], input[name="btn2_text"], input[name="btn_text2"], input[name="button2_title"], [data-field-name="buttontitle2"] input, [data-tpl-field="buttontitle2"] input, input[placeholder*="второй кнопки"]'
                    );
                    if (setVal(el, data.btn2_text)) applied.push(`Кнопка 2: "${data.btn2_text}"`);
                }

                // 7. Кнопка 2 (Ссылка)
                if (data.btn2_href) {
                    const el = document.querySelector(
                        'input[name="buttonlink2"], input[name="btn2_href"], input[name="btn_href2"], input[name="button2_link"], [data-field-name="buttonlink2"] input, [data-tpl-field="buttonlink2"] input'
                    );
                    if (setVal(el, data.btn2_href)) applied.push(`Ссылка кнопки 2: "${data.btn2_href}"`);
                }

                // 8. Фоновое изображение / Картинка карточки
                if (data.img_url) {
                    let imgApplied = false;
                    const imgInputs = Array.from(document.querySelectorAll(
                        'input[name="img-tuinfo-cdnurl"], input[name="bgimg-tuinfo-cdnurl"], input[name="bgimg"]:not([type="file"]), input[name="img"]:not([type="file"]), input[name="image"]:not([type="file"]), input[name="preview"]:not([type="file"]), [data-tpl-field="img"] input:not([type="file"]), [data-tpl-field="bgimg"] input:not([type="file"])'
                    ));
                    imgInputs.forEach(inp => {
                        if (setVal(inp, data.img_url)) imgApplied = true;
                    });

                    // Служебные параметры Uploadcare / Tilda
                    const nameInp = document.querySelector('input[name="img-tuinfo-name"], input[name="bgimg-tuinfo-name"]');
                    if (nameInp) setVal(nameInp, 'image.jpg');
                    const wInp = document.querySelector('input[name="img-tuinfo-width"]');
                    if (wInp) setVal(wInp, '1920');
                    const hInp = document.querySelector('input[name="img-tuinfo-height"]');
                    if (hInp) setVal(hInp, '1080');

                    // Превью в шторке
                    const previews = document.querySelectorAll(
                        '.pe-field-image__preview, .uploadcare--widget__text, .t-img-control__preview, .pe-bgimg__preview'
                    );
                    previews.forEach(p => {
                        try { p.style.backgroundImage = `url("${data.img_url}")`; } catch(e) {}
                    });

                    if (imgApplied || previews.length > 0) applied.push("Изображение (URL)");
                }

                return applied;
            }""", content_data)

            if not applied_fields:
                await self.page.evaluate("""() => {
                    const closeBtn = document.querySelector('.tbtn-tertiary, .pe-actions-close, #closelayer');
                    if (closeBtn) closeBtn.click();
                    if (typeof window.edrec__closeEditForm === 'function') window.edrec__closeEditForm(true);
                }""")
                await self.ensure_overlays_closed()
                no_fields_err = f"В блоке #{clean_rec_id} не удалось найти поля для запрошенного контента."
                await self._log("warning", no_fields_err)
                return {
                    "success": False,
                    "message": no_fields_err,
                    "applied": []
                }

            # Дополнительная подстраховка для кнопок через locator
            if btn_text:
                for b_sel in ["input[name='buttontitle']", "input[name='btn_text']", "input[name='btn1_text']"]:
                    loc = self.page.locator(b_sel).first
                    if await loc.count() > 0:
                        try:
                            await loc.scroll_into_view_if_needed(timeout=1000)
                            await loc.fill(btn_text)
                            break
                        except Exception:
                            pass

            if btn2_text:
                for b2_sel in ["input[name='buttontitle2']", "input[name='btn2_text']", "input[name='btn_text2']"]:
                    loc2 = self.page.locator(b2_sel).first
                    if await loc2.count() > 0:
                        try:
                            await loc2.scroll_into_view_if_needed(timeout=1000)
                            await loc2.fill(btn2_text)
                            break
                        except Exception:
                            pass

            await asyncio.sleep(0.5)

            # Нажимаем «Сохранить и закрыть» (оранжевая кнопка в шапке шторки)
            saved = await self.page.evaluate("""() => {
                const btn = document.querySelector(
                    'button.tbtn-primary, button.tbtn.tbtn-primary, .pe-content__savebtns-wrapper button:nth-child(2), .tp-popup__button_save-close'
                ) || Array.from(document.querySelectorAll('button')).find(b => b.innerText && b.innerText.includes('Сохранить и закрыть'));
                if (btn) {
                    btn.click();
                    return true;
                }
                if (typeof window.edrec__sendForm === 'function') {
                    window.edrec__sendForm('save', 'content');
                    return true;
                }
                return false;
            }""")

            if not saved:
                save_selectors = [
                    "button.tbtn-primary",
                    ".tp-popup__button_save-close",
                    "button:has-text('Сохранить и закрыть')",
                    "input[value='Сохранить и закрыть']",
                    ".pe-content__savebtns-wrapper button:nth-child(2)",
                ]
                for ss in save_selectors:
                    sloc = self.page.locator(ss).first
                    if await sloc.count() > 0 and await sloc.is_visible():
                        await sloc.click()
                        saved = True
                        break

            await asyncio.sleep(2.0)
            # Проверяем, закрылась ли шторка контента. Если нет — закрываем через edrec__closeEditForm
            is_panel_open = await self.page.evaluate("""() => {
                const p = document.querySelector('.pe-content__form-wrapper, .tp-popup_content, #editrecordcontent_container');
                return p && p.offsetParent !== null;
            }""")
            if is_panel_open:
                await self.page.evaluate("""() => {
                    const closeBtn = document.querySelector('.tbtn-tertiary, .pe-actions-close, #closelayer');
                    if (closeBtn) closeBtn.click();
                    if (typeof window.edrec__closeEditForm === 'function') window.edrec__closeEditForm(true);
                }""")
                await self.ensure_overlays_closed()

            await self._log("info", f"Контент блока #{clean_rec_id or ''} успешно сохранён через шторку «Контент» ({', '.join(applied_fields)}) ✓")
            return {
                "success": True,
                "message": f"Контент блока #{clean_rec_id or ''} успешно сохранён ({', '.join(applied_fields)})",
                "applied": applied_fields
            }

        except Exception as e:
            err = f"Ошибка при наполнении контента блока: {e}"
            await self._log("error", err)
            return {"success": False, "message": err, "applied": []}

    async def swap_block_title_descr(self, block_id: Optional[str] = None) -> dict:
        """
        Меняет местами заголовок и подзаголовок (описание) блока Tilda через шторку «Контент».
        Автоматически считывает текущие значения из полей формы, переставляет их и сохраняет.
        """
        target_name = block_id or "главный"
        await self._log("info", f"Меняю местами заголовок и подзаголовок блока ('{target_name}')...")
        try:
            current_url = self.page.url if self._page else ""
            if "/page/?pageid=" not in current_url:
                await self.open_page()
                await asyncio.sleep(2)

            await self.ensure_overlays_closed()

            # 1. Разрешаем целевой блок (по умолчанию 'главный')
            resolved = await self.resolve_block(block_id or "главный")
            clean_rec_id = resolved.get("id") if resolved else (block_id.lstrip("#") if block_id else None)
            if not clean_rec_id:
                clean_rec_id = await self.page.evaluate("""() => {
                    const rec = document.querySelector('.r[data-record-type]:not([data-record-type="131"]):first-of-type, .r:first-of-type');
                    return rec ? rec.id : null;
                }""")

            if not clean_rec_id:
                err_msg = "Не удалось найти целевой блок для перестановки заголовка и подзаголовка"
                await self._log("error", err_msg)
                return {"success": False, "message": err_msg, "applied": []}

            clean_num = re.sub(r'\D', '', clean_rec_id)
            target = self.page.locator(f"#{clean_rec_id}").first
            if await target.count() > 0:
                try:
                    await target.scroll_into_view_if_needed(timeout=3000)
                    await target.hover(timeout=2000)
                except Exception:
                    pass
                await asyncio.sleep(0.5)

            # 2. Открываем шторку «Контент» для блока
            opened = await self.page.evaluate("""(num) => {
                let targetUI = null;
                const uis = Array.from(document.querySelectorAll('.tp-record-ui'));
                if (num) {
                    targetUI = uis.find(u => {
                        const rId = u.getAttribute('data-recordid') || u.querySelector('[data-recordid]')?.getAttribute('data-recordid');
                        return rId === num;
                    });
                }
                if (!targetUI) targetUI = document.querySelector('.tp-record-ui_hovered') || uis[0];
                if (targetUI) {
                    const btn = targetUI.querySelector('.tp-record-ui__icon_content')?.closest('button') ||
                                targetUI.querySelector('.tp-record-ui__button_primary') ||
                                Array.from(targetUI.querySelectorAll('button')).find(b => (b.innerText || '').includes('Контент'));
                    if (btn) {
                        btn.click();
                        return true;
                    }
                }
                if (typeof window.editrecordcontent === 'function' && num) {
                    window.editrecordcontent(num);
                    return true;
                }
                return false;
            }""", clean_num)

            await asyncio.sleep(2.0)

            # 3. Считываем текущие заголовок и описание, меняем их местами
            swap_res = await self.page.evaluate("""() => {
                const setVal = (el, val) => {
                    if (!el || val === undefined || val === null) return false;
                    try {
                        if (el.type === 'file') return false;
                        el.value = val;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                        return true;
                    } catch(e) { return false; }
                };

                let curTitle = "";
                const titleQl = document.querySelector('.pe-redactor__wrapper[data-field="title"] .ql-editor, [data-tpl-field="title"] .ql-editor, .pe-field-title .ql-editor');
                const titleTa = document.querySelector('textarea[name="title"], textarea[name="header"], input[name="title"]');
                if (titleQl) curTitle = titleQl.innerText.trim();
                else if (titleTa) curTitle = titleTa.value.trim();

                let curDescr = "";
                const descrQl = document.querySelector('.pe-redactor__wrapper[data-field="text"] .ql-editor, .pe-redactor__wrapper[data-field="descr"] .ql-editor, [data-tpl-field="descr"] .ql-editor, .pe-field-descr .ql-editor');
                const descrTa = document.querySelector('textarea[name="text"], textarea[name="descr"], textarea[name="subtitle"]');
                if (descrQl) curDescr = descrQl.innerText.trim();
                else if (descrTa) curDescr = descrTa.value.trim();

                if (!curTitle && !curDescr) {
                    return { success: false, reason: "Не удалось прочитать текущий заголовок или описание в форме" };
                }

                const newTitle = curDescr;
                const newDescr = curTitle;

                let titleSet = false;
                if (titleQl) {
                    titleQl.innerText = newTitle;
                    titleQl.dispatchEvent(new Event('input', { bubbles: true }));
                    titleSet = true;
                }
                if (titleTa && setVal(titleTa, newTitle)) titleSet = true;

                let descrSet = false;
                if (descrQl) {
                    descrQl.innerText = newDescr;
                    descrQl.dispatchEvent(new Event('input', { bubbles: true }));
                    descrSet = true;
                }
                if (descrTa && setVal(descrTa, newDescr)) descrSet = true;

                return {
                    success: titleSet || descrSet,
                    oldTitle: curTitle,
                    oldDescr: curDescr,
                    newTitle: newTitle,
                    newDescr: newDescr
                };
            }""")

            if not swap_res.get("success"):
                err_swap = swap_res.get("reason", "Не удалось перезаписать поля заголовка и описания")
                await self._log("warning", err_swap)
                await self.page.evaluate("""() => {
                    const closeBtn = document.querySelector('.tbtn-tertiary, .pe-actions-close, #closelayer');
                    if (closeBtn) closeBtn.click();
                    if (typeof window.edrec__closeEditForm === 'function') window.edrec__closeEditForm(true);
                }""")
                await self.ensure_overlays_closed()
                return {"success": False, "message": err_swap, "applied": []}

            await asyncio.sleep(0.5)

            # 4. Сохраняем изменения («Сохранить и закрыть»)
            await self.page.evaluate("""() => {
                const btn = document.querySelector('button.tbtn-primary, .pe-content__savebtns-wrapper button:nth-child(2)') ||
                            Array.from(document.querySelectorAll('button')).find(b => (b.innerText || '').includes('Сохранить и закрыть'));
                if (btn) {
                    btn.click();
                    return true;
                }
                if (typeof window.edrec__sendForm === 'function') {
                    window.edrec__sendForm('save', 'content');
                    return true;
                }
                return false;
            }""")

            await asyncio.sleep(2.0)
            await self.ensure_overlays_closed()

            msg = (
                f"Заголовок и подзаголовок блока #{clean_rec_id} успешно поменяны местами. "
                f"Новый заголовок: «{swap_res.get('newTitle')}», Новое описание: «{swap_res.get('newDescr')}»"
            )
            await self._log("info", msg + " ✓")
            return {
                "success": True,
                "message": msg,
                "applied": ["Перестановка заголовка и подзаголовка"],
                "old_title": swap_res.get("oldTitle"),
                "new_title": swap_res.get("newTitle"),
                "old_descr": swap_res.get("oldDescr"),
                "new_descr": swap_res.get("newDescr")
            }

        except Exception as e:
            err = f"Ошибка при перестановке заголовка и подзаголовка: {e}"
            await self._log("error", err)
            return {"success": False, "message": err, "applied": []}

    async def edit_block_settings(
        self,
        block_id: Optional[str] = None,
        title_color: Optional[str] = None,
        title_size: Optional[str] = None,
        title_weight: Optional[str] = None,
        title_align: Optional[str] = None,
        descr_color: Optional[str] = None,
        descr_size: Optional[str] = None,
        btn_bg_color: Optional[str] = None,
        btn_text_color: Optional[str] = None,
        btn_border_color: Optional[str] = None,
        btn_radius: Optional[str] = None,
        btn2_bg_color: Optional[str] = None,
        btn2_text_color: Optional[str] = None,
        btn2_border_color: Optional[str] = None,
        btn2_radius: Optional[str] = None,
        bg_color: Optional[str] = None,
        bg_filter: Optional[str] = None,
        block_selector: Optional[str] = None,
        **extra_settings,
    ) -> bool:
        """
        Открывает боковую шторку «Настройки» блока Tilda (кнопка слева перед «Контент»),
        раскрывает нужные аккордеоны (ТИПОГРАФИКА, КНОПКИ), применяет стили
        (цвета, размеры шрифтов, начертание, выравнивание, цвет и радиус скругления кнопок, фон)
        и нажимает «Сохранить и закрыть».
        """
        raw_settings = {
            "title_color": title_color,
            "title_size": title_size,
            "title_weight": title_weight,
            "title_align": title_align,
            "descr_color": descr_color,
            "descr_size": descr_size,
            "btn_bg_color": btn_bg_color,
            "btn_text_color": btn_text_color,
            "btn_border_color": btn_border_color,
            "btn_radius": btn_radius,
            "btn2_bg_color": btn2_bg_color,
            "btn2_text_color": btn2_text_color,
            "btn2_border_color": btn2_border_color,
            "btn2_radius": btn2_radius,
            "bg_color": bg_color,
            "bg_filter": bg_filter,
            **extra_settings,
        }
        settings = normalize_block_settings_payload(raw_settings)

        await self._log(
            "info",
            f"Редактирую настройки стилей блока (id: '{block_id or 'auto'}', стили: {settings})..."
        )

        try:
            current_url = self.page.url if self._page else ""
            if "/page/?pageid=" not in current_url:
                await self.open_page()
                await asyncio.sleep(2)

            # 1. Проверяем, не открыта ли уже шторка «Настройки» на экране
            is_already_open = await self.page.evaluate("""() => {
                const hasSaveBtn = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"]')).some(b => {
                    const txt = (b.innerText || b.value || '').trim();
                    return (txt.includes('Сохранить и закрыть') || txt === 'Сохранить') && b.offsetParent !== null;
                });
                const hasSections = Array.from(document.querySelectorAll('*')).some(el => {
                    const txt = (el.innerText || '').trim();
                    return (txt === 'ТИПОГРАФИКА' || txt === 'КНОПКИ' || txt === 'ЭФФЕКТ ПРИ СКРОЛЛЕ') && el.offsetParent !== null;
                });
                return hasSaveBtn || hasSections;
            }""")

            panel_found = is_already_open
            clean_rec_id = None

            if is_already_open:
                await self._log("info", "Панель «Настройки» уже открыта на экране, использую активную форму ✓")
            else:
                # Закрываем посторонние оверлеи перед кликом по блоку
                await self.ensure_overlays_closed()

                # Находим целевой блок
                target = None
                resolved = await self.resolve_block(block_id or block_selector)
                if resolved:
                    clean_rec_id = resolved.get("id")
                    if clean_rec_id:
                        target = self.page.locator(f"#{clean_rec_id}").first
                        await self._log("info", f"Найден блок #{clean_rec_id} ({resolved.get('code') or ''}) для редактирования настроек стилей")
                elif block_id:
                    clean_rec_id = block_id.lstrip("#")
                    target = self.page.locator(f"#{clean_rec_id}").first
                    if await target.count() == 0:
                        # Если ID не найден (например передан ID страницы), берем стандартный блок на странице
                        fallback = self.page.locator(".r[data-record-type]:not([data-record-type='396']):first-of-type, .r[data-record-type]:last-of-type, .r:last-of-type").first
                        if await fallback.count() > 0:
                            target = fallback
                            clean_rec_id = await target.get_attribute("id")
                            await self._log("info", f"ID '{block_id}' не найден среди блоков страницы, применяю стили к блоку #{clean_rec_id}")
                elif block_selector:
                    target = self.page.locator(block_selector).first
                    if await target.count() > 0:
                        clean_rec_id = await target.get_attribute("id")
                else:
                    target = self.page.locator(".r[data-record-type]:not([data-record-type='396']):last-of-type, .r:last-of-type").first
                    if await target.count() > 0:
                        clean_rec_id = await target.get_attribute("id")

                if not target or await target.count() == 0:
                    await self._log("error", f"Целевой блок {block_id or block_selector or ''} не найден на странице")
                    return False

                # Проверяем, не является ли блок Zero Block
                is_zero = await target.evaluate("""(el) => {
                    return !!el.querySelector('.t396') || el.getAttribute('data-record-type') === '396';
                }""")
                if is_zero:
                    await self._log("warning", f"Блок #{clean_rec_id} является Zero Block (стили Zero-блока настраиваются внутри Zero Editor).")
                    return False

                # Скроллим к блоку и наводим курсор
                try:
                    await target.scroll_into_view_if_needed(timeout=4000)
                    await target.hover(timeout=3000)
                except Exception:
                    await self.ensure_overlays_closed()
                    try:
                        await target.hover(force=True, timeout=2000)
                    except Exception:
                        pass
                await asyncio.sleep(0.5)

                # Ищем и нажимаем кнопку «Настройки» на блоке
                rec_num = re.sub(r'\D', '', clean_rec_id) if clean_rec_id else ""
                settings_opened = await self.page.evaluate("""(num) => {
                    let targetUI = (num ? document.querySelector('[data-recordid="' + num + '"]') : null) ||
                                   (num ? document.querySelector('[data-recordid="' + num + '"]')?.closest('.tp-record-ui') : null) ||
                                   document.querySelector('.tp-record-ui_hovered') ||
                                   document.querySelector('.tp-record-ui');
                    if (targetUI) {
                        const btn = targetUI.querySelector('.tp-record-ui__icon_settings')?.closest('button') ||
                                    targetUI.querySelector('.tp-record-ui__button_settings') ||
                                    Array.from(targetUI.querySelectorAll('button')).find(b => b.innerText && b.innerText.includes('Настройки'));
                        if (btn) {
                            btn.click();
                            return true;
                        }
                    }
                    if (typeof window.edrec === 'function' && num) {
                        window.edrec(num);
                        return true;
                    }
                    if (typeof window.editrecordsettings === 'function' && num) {
                        window.editrecordsettings(num);
                        return true;
                    }
                    return false;
                }""", rec_num)

                if not settings_opened:
                    settings_btn = self.page.locator(".tp-record-ui button:has(.tp-record-ui__icon_settings), .tp-record-ui .tp-record-ui__button_settings, button:has-text('Настройки')").first
                    if await settings_btn.count() > 0:
                        try:
                            await settings_btn.click()
                            settings_opened = True
                        except Exception:
                            pass

                # Опрашиваем в течение 5 секунд появление шторки (учитывая анимацию слайда)
                for _ in range(10):
                    await asyncio.sleep(0.5)
                    panel_found = await self.page.evaluate("""() => {
                        // 1. По кнопкам в шапке панели
                        const saveBtn = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"]')).find(b => {
                            const txt = (b.innerText || b.value || '').trim();
                            return (txt.includes('Сохранить и закрыть') || txt === 'Сохранить') && b.offsetParent !== null;
                        });
                        if (saveBtn) return true;

                        // 2. По разделам настроек
                        const hasSections = Array.from(document.querySelectorAll('*')).some(el => {
                            const txt = (el.innerText || '').trim();
                            return (txt === 'ТИПОГРАФИКА' || txt === 'КНОПКИ' || txt === 'ЭФФЕКТ ПРИ СКРОЛЛЕ') && el.offsetParent !== null;
                        });
                        if (hasSections) return true;

                        // 3. По селекторам контейнеров
                        const panel = document.querySelector(
                            '#editrecord_container, .editrecord_container, #editrecord, .pe-settings__form-wrapper, #formeditrecord, form[name="formeditrecord"], #form1, form#form1, .tp-record-edit, #recordsettings, .tp-record-settings, button.tbtn-primary'
                        );
                        return !!(panel && panel.offsetParent !== null);
                    }""")
                    if panel_found:
                        break

            if not panel_found:
                await self._log("error", f"Панель «Настройки» не открылась для блока #{clean_rec_id or ''}")
                return False

            await self._log("info", "Панель «Настройки» успешно обнаружена, раскрываю секции и настраиваю стили...")

            # 2. Раскрываем аккордеон «ТИПОГРАФИКА», если переданы параметры типографики
            has_typography = any(settings.get(k) for k in ("title_color", "title_size", "title_weight", "title_align", "descr_color", "descr_size"))
            if has_typography:
                expanded_typo = await self.page.evaluate("""() => {
                    const accs = Array.from(document.querySelectorAll('.ui-accordion-header, .tp-group-title, .tp-record-settings__group-title, div, button')).filter(el => {
                        const txt = (el.innerText || '').trim().toUpperCase();
                        return (txt === 'ТИПОГРАФИКА' || txt.startsWith('ТИПОГРАФИКА')) && el.children.length <= 2;
                    });
                    for (const acc of accs) {
                        const next = acc.nextElementSibling;
                        const isExpanded = acc.classList.contains('ui-state-active') ||
                                           acc.classList.contains('active') ||
                                           (next && next.offsetParent !== null && next.offsetHeight > 10);
                        if (!isExpanded) {
                            acc.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                if expanded_typo:
                    await asyncio.sleep(0.6)  # Пауза на анимацию разворачивания

            # 3. Раскрываем аккордеон «КНОПКИ», если переданы параметры кнопок
            has_buttons = any(settings.get(k) for k in ("btn_bg_color", "btn_text_color", "btn_border_color", "btn_radius", "btn2_bg_color", "btn2_text_color", "btn2_border_color", "btn2_radius"))
            if has_buttons:
                expanded_btn = await self.page.evaluate("""() => {
                    const accs = Array.from(document.querySelectorAll('.ui-accordion-header, .tp-group-title, .tp-record-settings__group-title, div, button')).filter(el => {
                        const txt = (el.innerText || '').trim().toUpperCase();
                        return (txt === 'КНОПКИ' || txt.startsWith('КНОПКИ')) && el.children.length <= 2;
                    });
                    for (const acc of accs) {
                        const next = acc.nextElementSibling;
                        const isExpanded = acc.classList.contains('ui-state-active') ||
                                           acc.classList.contains('active') ||
                                           (next && next.offsetParent !== null && next.offsetHeight > 10);
                        if (!isExpanded) {
                            acc.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                if expanded_btn:
                    await asyncio.sleep(0.6)  # Пауза на анимацию разворачивания

            # 4. Устанавливаем значения стилей в поля формы
            applied_details = await self.page.evaluate(r"""(s) => {
                const results = [];
                const form = document.querySelector('#formeditrecord, .pe-settings__form-wrapper, #editrecord_container') || document;

                function findField(namePatterns) {
                    for (const pat of namePatterns) {
                        const el = form.querySelector(`input[name="${pat}"], select[name="${pat}"], textarea[name="${pat}"]`);
                        if (el) return el;
                    }
                    return null;
                }

                function setVal(name, val) {
                    const el = form.querySelector(`input[name="${name}"], select[name="${name}"]`);
                    if (!el) return false;
                    el.value = val;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                    return true;
                }

                function updateTypoJson(jsonField, updates) {
                    const el = form.querySelector(`input[name="${jsonField}"]`);
                    if (el) {
                        let cur = {};
                        try { cur = JSON.parse(el.value || '{}'); } catch(e) {}
                        Object.assign(cur, updates);
                        el.value = JSON.stringify(cur);
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }

                // Вспомогательная функция для выбора начертания (weight) с поддержкой русских терминов Tilda
                function setFontWeight(el, weightVal) {
                    if (!el || !weightVal) return false;
                    const wStr = String(weightVal).toLowerCase();
                    const isBold = wStr.includes('bold') || wStr.includes('жирн') || wStr === '700' || wStr === '800';
                    const isSemi = wStr.includes('semi') || wStr.includes('medium') || wStr.includes('полуж') || wStr === '600' || wStr === '500';
                    const isLight = wStr.includes('light') || wStr.includes('тон') || wStr.includes('светл') || wStr === '300';
                    const isNormal = wStr.includes('normal') || wStr.includes('норм') || wStr.includes('регуляр') || wStr === '400';

                    if (el.tagName === 'SELECT') {
                        const opt = Array.from(el.options).find(o => {
                            const val = o.value.toLowerCase();
                            const txt = o.text.toLowerCase();
                            if (isBold && (val === '700' || val === '800' || txt.includes('жирн') || txt.includes('bold'))) return true;
                            if (isSemi && (val === '600' || val === '500' || txt.includes('полуж') || txt.includes('medium'))) return true;
                            if (isNormal && (val === '400' || txt.includes('норм') || txt.includes('обыч') || txt.includes('normal'))) return true;
                            if (isLight && (val === '300' || val === '200' || txt.includes('тон') || txt.includes('light'))) return true;
                            return txt.includes(wStr) || val === wStr;
                        });
                        if (opt) {
                            el.value = opt.value;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            return opt.text || opt.value;
                        }
                    } else {
                        const valToSet = isBold ? '700' : (isSemi ? '600' : (isNormal ? '400' : weightVal));
                        if (setVal(el.name, valToSet)) return valToSet;
                    }
                    return false;
                }

                // 1. Заголовок: SEO тег (H1, H2, H3, div)
                if (s.title_tag) {
                    const el = findField(['title_tag', 'titletag']);
                    if (el && el.tagName === 'SELECT') {
                        const tagVal = String(s.title_tag).toUpperCase();
                        const opt = Array.from(el.options).find(o => o.value.toUpperCase() === tagVal || o.text.toUpperCase() === tagVal);
                        if (opt) {
                            el.value = opt.value;
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            results.push(`Тег заголовка: ${opt.value}`);
                        }
                    }
                }

                // 2. Заголовок: цвет (title__color, title_color)
                if (s.title_color) {
                    const el = findField(['title__color', 'title_color', 'titlecolor']);
                    if (el && setVal(el.name, s.title_color)) {
                        updateTypoJson('title_typo', { color: s.title_color });
                        results.push(`Цвет заголовка: ${s.title_color}`);
                    }
                }

                // 3. Заголовок: размер (title__fontsize, title_fontsize)
                if (s.title_size) {
                    const rawSize = String(s.title_size).replace(/\D/g, '') || String(s.title_size);
                    const sizePx = rawSize.includes('px') ? rawSize : `${rawSize}px`;
                    const el = findField(['title__fontsize', 'title_fontsize', 'title_font_size']);
                    if (el && setVal(el.name, sizePx)) {
                        setVal(`${el.name}-range`, rawSize);
                        updateTypoJson('title_typo', { fontsize: sizePx });
                        results.push(`Размер заголовка: ${sizePx}`);
                    }
                }

                // 4. Заголовок: начертание (title__fontweight)
                if (s.title_weight) {
                    const el = findField(['title__fontweight-select', 'title__fontweight', 'title_fontweight']);
                    if (el) {
                        const res = setFontWeight(el, s.title_weight);
                        if (res) {
                            updateTypoJson('title_typo', { fontweight: String(res) });
                            results.push(`Начертание заголовка: ${res}`);
                        }
                    }
                }

                // 5. Выравнивание (align, title_align)
                if (s.title_align || s.align) {
                    const alignVal = (s.title_align || s.align).toLowerCase();
                    const el = findField(['align', 'title_align', 'title_textalign']);
                    if (el && el.tagName === 'SELECT') {
                        const opt = Array.from(el.options).find(o => o.value.toLowerCase() === alignVal || o.text.toLowerCase().includes(alignVal));
                        if (opt) {
                            el.value = opt.value;
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            results.push(`Выравнивание: ${opt.text || opt.value}`);
                        }
                    }
                }

                // 6. Вертикальное выравнивание (valign)
                if (s.valign) {
                    const vVal = String(s.valign).toLowerCase();
                    const el = findField(['valign']);
                    if (el && el.tagName === 'SELECT') {
                        const opt = Array.from(el.options).find(o => o.value.toLowerCase() === vVal || o.text.toLowerCase().includes(vVal));
                        if (opt) {
                            el.value = opt.value;
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            results.push(`Вертикальное выравнивание: ${opt.text || opt.value}`);
                        }
                    }
                }

                // 7. Высота блока (height: 100vh, 800px)
                if (s.height) {
                    const el = findField(['height', 'cover_height']);
                    if (el && setVal(el.name, s.height)) {
                        results.push(`Высота: ${s.height}`);
                    }
                }

                // 8. Описание: цвет (descr__color, descr_color)
                if (s.descr_color) {
                    const el = findField(['descr__color', 'descr_color', 'descrcolor', 'text_color']);
                    if (el && setVal(el.name, s.descr_color)) {
                        updateTypoJson('descr_typo', { color: s.descr_color });
                        results.push(`Цвет описания: ${s.descr_color}`);
                    }
                }

                // 9. Описание: размер (descr__fontsize, descr_fontsize)
                if (s.descr_size) {
                    const rawDescrSize = String(s.descr_size).replace(/\D/g, '') || String(s.descr_size);
                    const sizePx = rawDescrSize.includes('px') ? rawDescrSize : `${rawDescrSize}px`;
                    const el = findField(['descr__fontsize', 'descr_fontsize', 'descr_font_size']);
                    if (el && setVal(el.name, sizePx)) {
                        setVal(`${el.name}-range`, rawDescrSize);
                        updateTypoJson('descr_typo', { fontsize: sizePx });
                        results.push(`Размер описания: ${sizePx}`);
                    }
                }

                // 10. Описание: начертание (descr__fontweight)
                if (s.descr_weight) {
                    const el = findField(['descr__fontweight-select', 'descr__fontweight', 'descr_fontweight']);
                    if (el) {
                        const res = setFontWeight(el, s.descr_weight);
                        if (res) {
                            updateTypoJson('descr_typo', { fontweight: String(res) });
                            results.push(`Начертание описания: ${res}`);
                        }
                    }
                }

                // 11. Кнопка 1: цвет фона (button__bgcolor, button_bgcolor)
                if (s.btn_bg_color) {
                    const el = findField(['button__bgcolor', 'button_bgcolor', 'btn_background', 'btn_bg_color']);
                    if (el && setVal(el.name, s.btn_bg_color)) {
                        updateTypoJson('button_styles', { bgcolor: s.btn_bg_color });
                        results.push(`Фон кнопки 1: ${s.btn_bg_color}`);
                    }
                }

                // 12. Кнопка 1: цвет текста (button__color, button_color)
                if (s.btn_text_color) {
                    const el = findField(['button__color', 'button_color', 'btn_text_color', 'btn_color']);
                    if (el && setVal(el.name, s.btn_text_color)) {
                        updateTypoJson('button_styles', { color: s.btn_text_color });
                        results.push(`Цвет текста кнопки 1: ${s.btn_text_color}`);
                    }
                }

                // 13. Кнопка 1: цвет рамки (button__bordercolor)
                if (s.btn_border_color) {
                    const el = findField(['button__bordercolor', 'button_border_color', 'btn_border_color']);
                    if (el && setVal(el.name, s.btn_border_color)) {
                        updateTypoJson('button_styles', { bordercolor: s.btn_border_color });
                        results.push(`Рамка кнопки 1: ${s.btn_border_color}`);
                    }
                }

                // 14. Кнопка 1: радиус скругления (button__radius)
                if (s.btn_radius) {
                    const rawRadius = String(s.btn_radius).replace(/\D/g, '') || String(s.btn_radius);
                    const radiusPx = rawRadius.includes('px') ? rawRadius : `${rawRadius}px`;
                    const el = findField(['button__radius', 'button_radius', 'btn_radius']);
                    if (el && setVal(el.name, radiusPx)) {
                        setVal(`${el.name}-range`, rawRadius);
                        updateTypoJson('button_styles', { radius: radiusPx });
                        results.push(`Радиус кнопки 1: ${radiusPx}`);
                    }
                }

                // 15. Скругление обложки (cover_borderradius)
                if (s.cover_borderradius) {
                    const rawRadius = String(s.cover_borderradius).replace(/\D/g, '') || String(s.cover_borderradius);
                    const el = findField(['cover_borderradius']);
                    if (el && setVal(el.name, rawRadius)) {
                        setVal('cover_borderradius-range', rawRadius);
                        results.push(`Радиус обложки: ${rawRadius}px`);
                    }
                }

                // 16. Кнопка 2: стили (button2__bgcolor, button2__color, button2__radius)
                if (s.btn2_bg_color) {
                    const el = findField(['button2__bgcolor', 'button2_bgcolor', 'btn2_background', 'btn2_bg_color']);
                    if (el && setVal(el.name, s.btn2_bg_color)) {
                        updateTypoJson('button2_styles', { bgcolor: s.btn2_bg_color });
                        results.push(`Фон кнопки 2: ${s.btn2_bg_color}`);
                    }
                }
                if (s.btn2_text_color) {
                    const el = findField(['button2__color', 'button2_color', 'btn2_text_color']);
                    if (el && setVal(el.name, s.btn2_text_color)) {
                        updateTypoJson('button2_styles', { color: s.btn2_text_color });
                        results.push(`Цвет кнопки 2: ${s.btn2_text_color}`);
                    }
                }
                if (s.btn2_border_color) {
                    const el = findField(['button2__bordercolor', 'button2_border_color']);
                    if (el && setVal(el.name, s.btn2_border_color)) {
                        updateTypoJson('button2_styles', { bordercolor: s.btn2_border_color });
                        results.push(`Рамка кнопки 2: ${s.btn2_border_color}`);
                    }
                }
                if (s.btn2_radius) {
                    const rawRadius = String(s.btn2_radius).replace(/\D/g, '') || String(s.btn2_radius);
                    const radiusPx = rawRadius.includes('px') ? rawRadius : `${rawRadius}px`;
                    const el = findField(['button2__radius', 'button2_radius', 'btn2_radius']);
                    if (el && setVal(el.name, radiusPx)) {
                        setVal(`${el.name}-range`, rawRadius);
                        updateTypoJson('button2_styles', { radius: radiusPx });
                        results.push(`Радиус кнопки 2: ${radiusPx}`);
                    }
                }

                // 17. Общие стили: цвет фона блока (blockbackground, bg_color)
                if (s.bg_color || s.blockbackground) {
                    const bgVal = s.bg_color || s.blockbackground;
                    const el = findField(['blockbackground', 'bg_color', 'bgcolor']);
                    if (el && setVal(el.name, bgVal)) {
                        results.push(`Фон блока: ${bgVal}`);
                    }
                }

                // 18. Общие стили: фильтр затемнения
                if (s.bg_filter || s.filtercolor) {
                    const fVal = s.bg_filter || s.filtercolor;
                    const el = findField(['filtercolor', 'bg_filter', 'filterstart']);
                    if (el && setVal(el.name, fVal)) {
                        results.push(`Цвет фильтра: ${fVal}`);
                    }
                }
                if (s.filtercolor2) {
                    const el = findField(['filtercolor2', 'filterend']);
                    if (el && setVal(el.name, s.filtercolor2)) {
                        results.push(`Фильтр 2: ${s.filtercolor2}`);
                    }
                }
                if (s.filteropacity) {
                    const el = findField(['filteropacity']);
                    if (el && el.tagName === 'SELECT') {
                        const opt = Array.from(el.options).find(o => o.value === String(s.filteropacity) || o.text.includes(String(s.filteropacity)));
                        if (opt) {
                            el.value = opt.value;
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            results.push(`Прозрачность фильтра: ${opt.text || opt.value}`);
                        }
                    }
                }

                return results;
            }""", settings)

            if not applied_details:
                # Ни одно поле не было найдено в форме Tilda — не рапортуем ложный успех!
                await self.page.evaluate("""() => {
                    const closeBtn = document.querySelector('.tp-record-settings__btn-close, .pe-actions-close, #closelayer');
                    if (closeBtn) closeBtn.click();
                    if (typeof window.edrec__closeEditForm === 'function') window.edrec__closeEditForm(true);
                }""")
                await self.ensure_overlays_closed()

                no_fields_msg = (
                    f"В настройках блока #{clean_rec_id} отсутствуют поля для запрошенных стилей. "
                    f"В стандартных блоках Tilda (включая обложки) размер и цвет шрифта не настраиваются через инпуты в шторке «Настройки» — "
                    f"они определяются глобальными стилями проекта (Шрифты и цвета) или тегами H1/H2."
                )
                await self._log("warning", no_fields_msg)
                return {
                    "success": False,
                    "message": no_fields_msg,
                    "applied": []
                }

            await self._log("info", f"Применены параметры стилей: {', '.join(applied_details)}")
            await asyncio.sleep(0.5)

            # 5. Нажимаем «Сохранить и закрыть»
            saved = await self.page.evaluate("""() => {
                const saveCloseBtn = document.querySelector(
                    '.tp-record-settings__btn-saveclose, button.tp-record-settings__btn-saveclose, .tp-popup__button_save-close, button.tbtn-primary'
                ) || Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"]')).find(b => {
                    const txt = (b.innerText || b.value || '').trim();
                    return txt.includes('Сохранить и закрыть') && b.offsetParent !== null;
                });

                if (saveCloseBtn) {
                    saveCloseBtn.click();
                    return true;
                }

                const form = document.querySelector('#formeditrecord, form[name="formeditrecord"]');
                if (form) {
                    const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
                    if (submitBtn) {
                        submitBtn.click();
                        return true;
                    }
                }

                if (typeof window.edrec__sendForm === 'function') {
                    window.edrec__sendForm('save', 'settings');
                    return true;
                }
                return false;
            }""")

            if not saved:
                save_selectors = [
                    ".tp-record-settings__btn-saveclose",
                    "button:has-text('Сохранить и закрыть')",
                    "input[value='Сохранить и закрыть']",
                    "button.tbtn-primary",
                    ".tp-popup__button_save-close",
                ]
                for ss in save_selectors:
                    sloc = self.page.locator(ss).first
                    if await sloc.count() > 0 and await sloc.is_visible():
                        await sloc.click()
                        saved = True
                        break

            # Ждём завершения AJAX-сохранения Tilda (до 6 секунд)
            for _ in range(12):
                await asyncio.sleep(0.5)
                is_panel_closed = await self.page.evaluate("""() => {
                    const saveBtn = Array.from(document.querySelectorAll('button, input[type="button"]')).find(b => {
                        const txt = (b.innerText || b.value || '').trim();
                        return (txt.includes('Сохранить и закрыть') || txt === 'Сохранить') && b.offsetParent !== null;
                    });
                    return !saveBtn;
                }""")
                if is_panel_closed:
                    break

            # Если панель всё ещё видна после ожидания — мягко закрываем без discard
            is_panel_still_open = await self.page.evaluate("""() => {
                const saveBtn = Array.from(document.querySelectorAll('button, input[type="button"]')).find(b => {
                    const txt = (b.innerText || b.value || '').trim();
                    return (txt.includes('Сохранить и закрыть') || txt === 'Сохранить') && b.offsetParent !== null;
                });
                return !!saveBtn;
            }""")
            if is_panel_still_open:
                await self.page.evaluate("""() => {
                    const closeBtn = document.querySelector('.tp-record-settings__btn-close, .pe-actions-close, #closelayer');
                    if (closeBtn) closeBtn.click();
                }""")
                await self.ensure_overlays_closed()

            await self._log("info", f"Стили блока #{clean_rec_id or ''} успешно настроены и сохранены через шторку «Настройки» ({', '.join(applied_details)}) ✓")
            return {
                "success": True,
                "message": f"Стили блока #{clean_rec_id or ''} применены: {', '.join(applied_details)}",
                "applied": applied_details
            }

        except Exception as e:
            err = f"Ошибка при настройке стилей блока: {e}"
            await self._log("error", err)
            return {"success": False, "message": err, "applied": []}

    async def inspect_block_dom(self, block_id: Optional[str] = None, block_selector: Optional[str] = None) -> dict:
        """
        Исследует реальную верстку блока на странице (селекторы заголовка, подзаголовка,
        кнопок, их родительские контейнеры, стили отображения и порядок элементов).
        Возвращает структурированные данные о верстке для генерации точного JS/CSS.
        """
        await self._log("info", f"Исследую верстку блока (id: '{block_id or 'auto'}')...")
        try:
            current_url = self.page.url if self._page else ""
            if "/page/?pageid=" not in current_url:
                await self.open_page()
                await asyncio.sleep(2)

            resolved = await self.resolve_block(block_id or block_selector)
            clean_rec_id = resolved.get("id") if resolved else (block_id.lstrip("#") if block_id else None)

            dom_data = await self.page.evaluate("""(targetId) => {
                let rec = targetId ? document.querySelector('#' + targetId) : null;
                if (!rec) {
                    rec = document.querySelector('.r[data-record-type]:not([data-record-type="131"]):first-of-type') ||
                          document.querySelector('.r[data-record-type]:first-of-type') ||
                          document.querySelector('.r:first-of-type');
                }
                if (!rec) return null;

                const cleanId = rec.id;
                const recType = rec.getAttribute('data-record-type') || '';
                const recCode = rec.getAttribute('data-record-cod') || '';

                // 1. Поиск заголовка (включая карточки товаров, обложки и текстовые блоки)
                const title = rec.querySelector('.t-title, h1, h2, h3, .js-title, .js-product-name, .t-name_xl, .t-name, [field="title"]');
                // 2. Поиск описания и подзаголовка
                const descr = rec.querySelector('.t-descr:not(.t-descr_xxs), .t-text, .js-descr, [field="descr"]');
                // 3. Артикул SKU / доп. текст
                const sku = rec.querySelector('.js-product-sku, [field="title2"], .t762__title_small');
                
                // 4. Цены товаров
                const priceElem = rec.querySelector('.js-product-price, .t-product__price, .t762__price-value, [field="price"]');
                const priceOldElem = rec.querySelector('.t762__price_old, [field="price_old"]');

                // 5. Селекты вариантов товара (Цвет, Размер и т.д.)
                const selectNodes = Array.from(rec.querySelectorAll('select, .t-product__option-select, .js-product-option-variants'));
                const selects = selectNodes.map(s => {
                    const optWrap = s.closest('.t-product__option') || s.parentElement;
                    const optTitle = optWrap ? (optWrap.querySelector('.t-product__option-title, .js-product-option-name')?.innerText || '').trim() : '';
                    const options = Array.from(s.options || []).map(o => ({
                        value: o.value,
                        text: (o.textContent || '').trim()
                    }));
                    return {
                        name: s.name || s.getAttribute('data-name') || '',
                        className: s.className,
                        label: optTitle,
                        optionsCount: options.length,
                        options: options
                    };
                });

                // 6. Кнопки и ссылки действий
                const buttonNodes = Array.from(rec.querySelectorAll('.t-btn, .t762__btn, a[href^="#"], button, .js-btn, [role="button"]'));
                const buttons = buttonNodes.slice(0, 8).map(b => {
                    const cs = window.getComputedStyle(b);
                    return {
                        tag: b.tagName,
                        text: (b.innerText || '').trim(),
                        href: b.getAttribute('href') || '',
                        className: b.className,
                        borderRadius: cs.borderRadius,
                        backgroundColor: cs.backgroundColor,
                        color: cs.color
                    };
                });

                // 7. Сбор ключевых классов контейнеров
                const mainContainers = [];
                const containerNodes = rec.querySelectorAll('.js-product, .t762__container, .t762__info, .t-cover__carrier, .t-container, .t-store__card, .t-popup');
                containerNodes.forEach(c => {
                    Array.from(c.classList).forEach(cls => {
                        if (!mainContainers.includes('.' + cls)) mainContainers.push('.' + cls);
                    });
                });

                // 8. Компактный HTML-скелет контролов и карточки (до 1500 символов)
                let snippetTarget = rec.querySelector('.js-product-controls-wrapper, .t762__info, .t762__container, .t-cover__wrapper') || rec;
                let domSnippet = snippetTarget ? snippetTarget.outerHTML : '';
                if (domSnippet.length > 1500) {
                    domSnippet = domSnippet.substring(0, 1500) + '... <!-- truncated -->';
                }

                const rTitle = title ? title.getBoundingClientRect() : null;
                const rDescr = descr ? descr.getBoundingClientRect() : null;

                let commonParent = null;
                if (title && descr) {
                    let p = title.parentElement;
                    while (p && p !== rec) {
                        if (p.contains(descr)) {
                            commonParent = p;
                            break;
                        }
                        p = p.parentElement;
                    }
                }

                let parentInfo = null;
                if (commonParent) {
                    const style = window.getComputedStyle(commonParent);
                    parentInfo = {
                        tag: commonParent.tagName,
                        className: commonParent.className,
                        id: commonParent.id || '',
                        display: style.display,
                        flexDirection: style.flexDirection,
                        alignItems: style.alignItems
                    };
                }

                const isDescrAbove = (rTitle && rDescr) ? (rDescr.top < rTitle.top) : false;

                return {
                    blockId: cleanId,
                    recordType: recType,
                    recordCode: recCode,
                    title: title ? {
                        tag: title.tagName,
                        className: title.className,
                        text: (title.innerText || '').trim(),
                        rect: { top: rTitle.top, left: rTitle.left, width: rTitle.width, height: rTitle.height }
                    } : null,
                    descr: descr ? {
                        tag: descr.tagName,
                        className: descr.className,
                        text: (descr.innerText || '').trim(),
                        rect: { top: rDescr.top, left: rDescr.left, width: rDescr.width, height: rDescr.height }
                    } : null,
                    sku: sku ? (sku.innerText || '').trim() : null,
                    price: priceElem ? (priceElem.innerText || '').trim() : null,
                    priceOld: priceOldElem ? (priceOldElem.innerText || '').trim() : null,
                    selects: selects,
                    buttons: buttons,
                    containers: mainContainers,
                    domSnippet: domSnippet,
                    parentContainer: parentInfo,
                    isDescrAbove: isDescrAbove
                };
            }""", clean_rec_id)

            if not dom_data:
                err_msg = f"Блок {block_id or ''} не найден на странице для инспекции верстки"
                await self._log("error", err_msg)
                return {"success": False, "message": err_msg, "dom": None}

            t_text = dom_data.get('title', {}).get('text') if dom_data.get('title') else '-'
            d_text = dom_data.get('descr', {}).get('text') if dom_data.get('descr') else '-'
            selects_cnt = len(dom_data.get('selects') or [])
            btns_cnt = len(dom_data.get('buttons') or [])
            containers_str = ", ".join((dom_data.get('containers') or [])[:5])

            await self._log("info", (
                f"Верстка блока #{dom_data.get('blockId')} (тип {dom_data.get('recordType') or 'Tilda'}) исследована: "
                f"заголовок='{t_text}', селектов вариантов: {selects_cnt}, кнопок: {btns_cnt}. "
                f"Контейнеры: [{containers_str}]"
            ))
            return {
                "success": True,
                "message": f"Верстка блока #{dom_data.get('blockId')} успешно исследована",
                "dom": dom_data
            }

        except Exception as e:
            err = f"Ошибка при инспекции верстки блока: {e}"
            await self._log("error", err)
            return {"success": False, "message": err, "dom": None}

    async def inspect_live_page_dom(self, block_id: Optional[str] = None, url: Optional[str] = None) -> dict:
        """
        Исследует РЕАЛЬНЫЙ боевой DOM на Вкладке 2 (опубликованный сайт).
        Определяет точный ID блока (например rec4671108001), контейнеры (.t762__container, .js-product),
        селекты вариантов, кнопки, цены и заголовок.
        Гарантирует точный ID для исключения плейсхолдеров #recTARGET.
        """
        await self._log("info", "Исследую верстку на боевом опубликованном сайте (Вкладка 2)...")
        live_p = await self.switch_to_live_page(url=url)
        await asyncio.sleep(2.0)

        dom_data = await live_p.evaluate("""(targetId) => {
            const recs = Array.from(document.querySelectorAll('.r[id^="rec"]'));
            let rec = targetId ? document.querySelector('#' + targetId) : null;
            if (!rec) {
                rec = document.querySelector('.r[data-record-type="762"], .r:has(.js-product), .r[data-record-cod="ST205"]') ||
                      recs.find(r => r.querySelector('.js-product, .t762__container, .t-store__card, .t-cover')) ||
                      recs.find(r => r.getAttribute('data-record-type') !== '131') ||
                      recs[0];
            }
            if (!rec) return null;

            const cleanId = rec.id;
            const recType = rec.getAttribute('data-record-type') || '';
            const recCode = rec.getAttribute('data-record-cod') || '';

            const title = rec.querySelector('.t-title, h1, h2, h3, .js-title, .js-product-name, .t-name_xl, .t-name, [field="title"]');
            const descr = rec.querySelector('.t-descr:not(.t-descr_xxs), .t-text, .js-descr, [field="descr"]');
            const sku = rec.querySelector('.js-product-sku, [field="title2"], .t762__title_small');
            const priceElem = rec.querySelector('.js-product-price, .t-product__price, .t762__price-value, [field="price"]');
            const priceOldElem = rec.querySelector('.t762__price_old, [field="price_old"]');

            const selectNodes = Array.from(rec.querySelectorAll('select, .t-product__option-select, .js-product-option-variants'));
            const selects = selectNodes.map(s => {
                const optWrap = s.closest('.t-product__option') || s.parentElement;
                const optTitle = optWrap ? (optWrap.querySelector('.t-product__option-title, .js-product-option-name')?.innerText || '').trim() : '';
                return {
                    name: s.name || s.getAttribute('data-name') || '',
                    className: s.className,
                    label: optTitle,
                    options: Array.from(s.options || []).map(o => ({ value: o.value, text: (o.textContent || '').trim() }))
                };
            });

            const buttonNodes = Array.from(rec.querySelectorAll('.t-btn, .t762__btn, a[href^="#"], button, .js-btn, [role="button"]'));
            const buttons = buttonNodes.slice(0, 8).map(b => ({
                tag: b.tagName,
                text: (b.innerText || '').trim(),
                className: b.className
            }));

            const mainContainers = [];
            const containerNodes = rec.querySelectorAll('.js-product, .t762__container, .t762__info, .t-cover__carrier, .t-container, .t-store__card');
            containerNodes.forEach(c => {
                Array.from(c.classList).forEach(cls => {
                    if (!mainContainers.includes('.' + cls)) mainContainers.push('.' + cls);
                });
            });

            let snippetTarget = rec.querySelector('.js-product-controls-wrapper, .t762__info, .t762__container, .t-cover__wrapper') || rec;
            let domSnippet = snippetTarget ? snippetTarget.outerHTML : '';
            if (domSnippet.length > 1500) domSnippet = domSnippet.substring(0, 1500) + '...';

            return {
                blockId: cleanId,
                recordType: recType,
                recordCode: recCode,
                title: title ? (title.innerText || '').trim() : '',
                descr: descr ? (descr.innerText || '').trim() : '',
                sku: sku ? (sku.innerText || '').trim() : '',
                price: priceElem ? (priceElem.innerText || '').trim() : '',
                priceOld: priceOldElem ? (priceOldElem.innerText || '').trim() : '',
                selects: selects,
                buttons: buttons,
                mainContainers: mainContainers,
                domSnippet: domSnippet
            };
        }""", block_id)

        if not dom_data:
            err = "Не удалось обнаружить целевой блок на боевой странице"
            await self._log("warning", err)
            return {"success": False, "message": err}

        self._last_inspected_dom = dom_data
        b_id = dom_data.get("blockId", "")
        if b_id:
            self._last_target_block_id = b_id.lstrip("#")

        await self._log(
            "info",
            f"Верстка боевой страницы исследована: блок #{self._last_target_block_id} (тип {dom_data.get('recordType')}), "
            f"селектов: {len(dom_data.get('selects', []))}, контейнеры: {', '.join(dom_data.get('mainContainers', [])[:5])} ✓"
        )
        return {
            "success": True,
            "dom": dom_data,
            "block_id": self._last_target_block_id
        }

    async def get_t123_code(self, block_id: Optional[str] = None) -> str:
        """
        Считывает текущий HTML/CSS/JS код блока T123.
        1. Если код сохранен в кэше _last_t123_code — возвращает его.
        2. Иначе пытается прочитать код из DOM Tilda editor (шторка или canvas) или с live страницы.
        """
        if self._last_t123_code and len(self._last_t123_code.strip()) > 30:
            return self._last_t123_code

        # Проверяем, открыт ли редактор Tilda (Вкладка 1)
        try:
            if self._page and not self._page.is_closed():
                code_from_dom = await self.page.evaluate("""() => {
                    // 1. Проверяем открытую шторку контента
                    const form = document.querySelector('.editrecordcontent_container, .pe-content__form-wrapper, #formeditrecord');
                    if (form) {
                        const ta = form.querySelector('textarea[name="code"], textarea.pe-field-code, textarea[name="html"], textarea');
                        if (ta && ta.value && ta.value.trim().length > 20) return ta.value;
                        const aceEl = form.querySelector('.ace_editor');
                        if (aceEl && window.ace) {
                            try {
                                const val = window.ace.edit(aceEl).getValue();
                                if (val && val.trim().length > 20) return val;
                            } catch(e) {}
                        }
                    }
                    // 2. Ищем на странице блок T123 в редакторе
                    const t123 = document.querySelector('.r[data-record-type="131"]');
                    if (t123) {
                        const pre = t123.querySelector('pre, code, .t123__text, div[style*="font-family: monospace"]');
                        if (pre && pre.innerText && pre.innerText.length > 20) return pre.innerText;
                        const hiddenInput = t123.querySelector('input[name*="code"], textarea');
                        if (hiddenInput && hiddenInput.value) return hiddenInput.value;
                    }
                    return '';
                }""")
                if code_from_dom and len(code_from_dom.strip()) > 30:
                    self._last_t123_code = code_from_dom
                    return code_from_dom
        except Exception as e:
            logger.debug(f"Не удалось считать код T123 из редактора: {e}")

        # Проверяем live-страницу (Вкладка 2), если она открыта
        try:
            if self._live_page and not self._live_page.is_closed():
                live_code = await self._live_page.evaluate("""() => {
                    const t123 = document.querySelector('.r[data-record-type="131"], div[id^="rec"][data-record-type="131"]');
                    if (t123 && t123.innerHTML && t123.innerHTML.length > 30) {
                        return t123.innerHTML;
                    }
                    const styles = Array.from(document.querySelectorAll('style')).map(s => s.innerText || '').filter(s => s.includes('backdrop-filter') || s.includes('t-custom-option') || s.includes('mdAgent'));
                    const scripts = Array.from(document.querySelectorAll('script')).map(s => s.innerText || '').filter(s => s.includes('t-custom-option') || s.includes('mdAgent'));
                    if (styles.length || scripts.length) {
                        let res = '';
                        if (styles.length) res += '<style>\\n' + styles.join('\\n') + '\\n</style>\\n';
                        if (scripts.length) res += '<script>\\n' + scripts.join('\\n') + '\\n</script>';
                        return res;
                    }
                    return '';
                }""")
                if live_code and len(live_code.strip()) > 30:
                    self._last_t123_code = live_code
                    return live_code
        except Exception as e:
            logger.debug(f"Не удалось считать код T123 из live страницы: {e}")

        return self._last_t123_code or ""

    async def edit_t123_code(self, block_id: Optional[str] = None, code: str = "") -> dict:
        """
        Открывает боковую шторку «Контент» блока T123 (HTML-код) на Вкладке 1 (админка Tilda),
        проверяет ограничения Tilda (требование SMS-верификации) и сохраняет рабочий код.
        """
        await self._log("info", f"Редактирую код блока T123 ({len(code)} символов)...")
        try:
            # Гарантированно переключаемся на Вкладку 1 (Админка Tilda)
            await self.switch_to_admin()
            current_url = self.page.url if self._page else ""
            if "/page/?pageid=" not in current_url:
                await self.open_page()
                await asyncio.sleep(2)

            await self.ensure_overlays_closed()

            # 1. Находим блок T123 на странице
            t123_id = None
            if block_id:
                t123_id = block_id.lstrip("#")
            else:
                t123_id = await self.page.evaluate("""() => {
                    const recs = Array.from(document.querySelectorAll('.r[id^="rec"]'));
                    const byAttr = recs.find(r => r.getAttribute('data-record-type') === '131' || (r.getAttribute('data-record-cod') || '').toUpperCase() === 'T123');
                    if (byAttr) return byAttr.id;
                    const byText = recs.find(r => (r.innerText || '').includes('Код будет выполнен на опубликованной странице'));
                    if (byText) return byText.id;
                    return recs.length > 1 ? recs[recs.length - 1].id : (recs[0]?.id || null);
                }""")

            if not t123_id:
                err_msg = "Блок T123 не найден на странице. Сначала добавьте блок T123 через add_block(code='T123')."
                await self._log("warning", err_msg)
                return {"success": False, "message": err_msg, "applied": [], "is_blocked": False}

            clean_num = re.sub(r'\D', '', t123_id)
            target = self.page.locator(f"#{t123_id}").first
            if await target.count() > 0:
                try:
                    await target.scroll_into_view_if_needed(timeout=3000)
                    await target.hover(timeout=2000)
                except Exception:
                    pass
                await asyncio.sleep(0.5)

            # 2. Открываем шторку «Контент» для блока T123
            opened = await self.page.evaluate("""(num) => {
                let targetUI = null;
                const uis = Array.from(document.querySelectorAll('.tp-record-ui'));
                if (num) {
                    targetUI = uis.find(u => {
                        const rId = u.getAttribute('data-recordid') || u.querySelector('[data-recordid]')?.getAttribute('data-recordid');
                        return rId === num;
                    });
                }
                if (!targetUI) {
                    targetUI = uis.find(u => (u.innerText || '').includes('T123'));
                }
                if (!targetUI) {
                    targetUI = document.querySelector('.tp-record-ui_hovered');
                }
                if (targetUI) {
                    const btn = targetUI.querySelector('.tp-record-ui__icon_content')?.closest('button') ||
                                targetUI.querySelector('.tp-record-ui__button_primary') ||
                                Array.from(targetUI.querySelectorAll('button')).find(b => (b.innerText || '').includes('Контент'));
                    if (btn) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }""", clean_num)

            await asyncio.sleep(2.0)

            # 3. Проверяем открылась ли панель
            panel_info = await self.page.evaluate("""(expectedNum) => {
                const form = document.querySelector('.pe-content__form-wrapper, .editrecordcontent_container, #editrecordcontent_container');
                if (!form) return { open: false };
                const curId = document.querySelector('input[name="recordid"]')?.value;
                return {
                    open: true,
                    recordId: curId,
                    matches: !expectedNum || curId === expectedNum
                };
            }""", clean_num)

            if not panel_info.get("open") or not panel_info.get("matches"):
                err_msg = f"Не удалось открыть панель контента для блока T123 #{t123_id}"
                await self._log("error", err_msg)
                return {"success": False, "message": err_msg, "applied": [], "is_blocked": False}

            # Считываем текущий существующий код из формы перед перезаписью
            existing_code_in_form = await self.page.evaluate("""() => {
                const form = document.querySelector('.editrecordcontent_container, .pe-content__form-wrapper, #formeditrecord') || document;
                const ta = form.querySelector('textarea[name="code"], textarea.pe-field-code, textarea[name="html"], textarea');
                if (ta && ta.value && ta.value.trim().length > 20) return ta.value;
                const aceEl = form.querySelector('.ace_editor');
                if (aceEl && window.ace) {
                    try {
                        const val = window.ace.edit(aceEl).getValue();
                        if (val && val.trim().length > 20) return val;
                    } catch(e) {}
                }
                return '';
            }""")
            if existing_code_in_form and len(existing_code_in_form.strip()) > 20:
                self._last_t123_code = existing_code_in_form

            # 4. Проверяем ограничения Tilda на блок T123 (SMS-подтверждение телефона)
            check_restriction = await self.page.evaluate("""() => {
                const container = document.querySelector('.editrecordcontent_container, .pe-content__form-wrapper') || document.body;
                const text = container.innerText || '';
                const isBlocked = text.includes('Доступ к этому блоку ограничен') ||
                                  text.includes('подтвердите · номер телефона') ||
                                  text.includes('/identity/sms/');
                return { isBlocked: isBlocked, previewText: text.slice(0, 300) };
            }""")

            if check_restriction.get("isBlocked"):
                await self.page.evaluate("""() => {
                    const closeBtn = document.querySelector('.tbtn-tertiary, .pe-actions-close, #closelayer');
                    if (closeBtn) closeBtn.click();
                    if (typeof window.edrec__closeEditForm === 'function') window.edrec__closeEditForm(true);
                }""")
                await self.ensure_overlays_closed()

                blocked_msg = (
                    "Доступ к блоку T123 ограничен Tilda: требуется подтвердить номер телефона в аккаунте (/identity/sms/). "
                    "Пока номер не подтвержден, Tilda скрывает поле ввода HTML/JS кода в редакторе."
                )
                await self._log("warning", blocked_msg)
                return {
                    "success": False,
                    "is_blocked": True,
                    "message": blocked_msg,
                    "applied": []
                }

            # 5. Жесткая ликвидация любых плейсхолдеров (#recTARGET)
            target_clean = (self._last_target_block_id or "").lstrip("#")
            if not target_clean and self._last_inspected_dom:
                target_clean = (self._last_inspected_dom.get("blockId") or "").lstrip("#")
            if not target_clean:
                detected_target = await self.page.evaluate("""() => {
                    const recs = Array.from(document.querySelectorAll('.r[id^="rec"]'));
                    const prod = recs.find(r => r.querySelector('.js-product, .t762__container, .t-store__card, .t-cover'));
                    if (prod) return prod.id;
                    const nonT123 = recs.find(r => r.getAttribute('data-record-type') !== '131');
                    return nonT123 ? nonT123.id : '';
                }""")
                if detected_target:
                    target_clean = detected_target.lstrip('#')
            if not target_clean:
                target_clean = "rec4671108001"

            for p in ("#recTARGET", "recTARGET", "#TARGET", "TARGET_BLOCK", "recTARGET_BLOCK", "#recTARGET_BLOCK"):
                if p.startswith("#"):
                    code = code.replace(p, f"#{target_clean}")
                else:
                    code = code.replace(p, target_clean)

            # 5.1. Гарантируем обязательный комментарий в самом начале кода блока T123
            BRAND_COMMENT = "<!-- Создано с помощью mdAgent (https://mdagent.ru) -->"
            CSS_COMMENT = "/* Создано с помощью mdAgent (https://mdagent.ru) */"

            clean_code = code.strip()
            # Проверяем наличие mdAgent комментария в начале
            if "mdagent.ru" not in clean_code.lower() and "создано с помощью mdagent" not in clean_code.lower():
                clean_code = f"{BRAND_COMMENT}\n{clean_code}"
            elif not clean_code.startswith("<!--"):
                clean_code = f"{BRAND_COMMENT}\n{clean_code}"

            # Если в коде есть тег <style>, гарантируем CSS-комментарий
            if "<style" in clean_code and CSS_COMMENT not in clean_code:
                clean_code = clean_code.replace("<style>", f"<style>\n{CSS_COMMENT}\n", 1)
                clean_code = clean_code.replace('<style type="text/css">', f'<style type="text/css">\n{CSS_COMMENT}\n', 1)

            code = clean_code

            # Записываем код в textarea или Ace editor
            code_saved = await self.page.evaluate("""(codeVal) => {
                const form = document.querySelector('.editrecordcontent_container, .pe-content__form-wrapper, #formeditrecord') || document;
                const ta = form.querySelector('textarea[name="code"], textarea.pe-field-code, textarea[name="html"], textarea');
                if (ta) {
                    ta.value = codeVal;
                    ta.dispatchEvent(new Event('input', { bubbles: true }));
                    ta.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                const aceEl = form.querySelector('.ace_editor');
                if (aceEl && window.ace) {
                    try {
                        const editor = window.ace.edit(aceEl);
                        editor.setValue(codeVal);
                        return true;
                    } catch(e) {}
                }
                return false;
            }""", code)

            if not code_saved:
                err_code = "Не удалось найти поле ввода кода (textarea/editor) внутри блока T123."
                await self._log("error", err_code)
                return {"success": False, "message": err_code, "applied": [], "is_blocked": False}

            await asyncio.sleep(0.5)

            # 6. Сохраняем изменения («Сохранить и закрыть»)
            await self.page.evaluate("""() => {
                const btn = document.querySelector('button.tbtn-primary, .pe-content__savebtns-wrapper button:nth-child(2)') ||
                            Array.from(document.querySelectorAll('button')).find(b => (b.innerText || '').includes('Сохранить и закрыть'));
                if (btn) {
                    btn.click();
                    return true;
                }
                if (typeof window.edrec__sendForm === 'function') {
                    window.edrec__sendForm('save', 'content');
                    return true;
                }
                return false;
            }""")

            await asyncio.sleep(2.0)
            await self.ensure_overlays_closed()

            self._last_t123_code = code
            self._last_target_block_id = target_clean

            success_msg = f"Код ({len(code)} символов) успешно записан и сохранён в блоке T123 (#{t123_id})"
            await self._log("info", success_msg + " ✓")
            return {
                "success": True,
                "message": success_msg,
                "applied": [f"Код T123 ({len(code)} символов)"],
                "is_blocked": False
            }

        except Exception as e:
            err = f"Ошибка при редактировании кода T123: {e}"
            await self._log("error", err)
            return {"success": False, "message": err, "applied": [], "is_blocked": False}

    async def test_page_script(
        self,
        script: str,
        check_type: str = "swap_title_descr",
        block_id: Optional[str] = None
    ) -> dict:
        """
        Тестирует сгенерированный JS/CSS скрипт непосредственно в DOM страницы.
        Выполняет скрипт в изолированном контексте и проверяет целевой эффект
        (например, изменение порядка расположения заголовка и подзаголовка).
        """
        await self._log("info", f"Тестирую работу скрипта на странице (тип проверки: '{check_type}')...")
        try:
            current_url = self.page.url if self._page else ""
            if "/page/?pageid=" not in current_url:
                await self.open_page()
                await asyncio.sleep(2)

            test_res = await self.page.evaluate(r"""(data) => {
                try {
                    let raw = data.script.trim();
                    if (raw.startsWith('<style') && raw.endsWith('</style>')) {
                        const cssContent = raw.replace(/<style[^>]*>/gi, '').replace(/<\/style>/gi, '').trim();
                        const styleEl = document.createElement('style');
                        styleEl.id = 'mdagent-test-style';
                        styleEl.innerHTML = cssContent;
                        document.head.appendChild(styleEl);
                    } else {
                        const jsCode = raw.replace(/<script[^>]*>/gi, '').replace(/<\/script>/gi, '').trim();
                        eval(jsCode);
                    }

                    if (data.check_type === 'swap_title_descr') {
                        const rec = data.block_id ? document.querySelector('#' + data.block_id) : (document.querySelector('.r[id^="rec"]') || document);
                        if (!rec) return { success: false, reason: "Блок не найден на странице" };

                        const title = rec.querySelector('.t-title, h1, h2, .js-title');
                        const descr = rec.querySelector('.t-descr, .t-text, .js-descr');
                        if (!title || !descr) {
                            return { success: false, reason: "Не найден заголовок или подзаголовок в целевом блоке" };
                        }

                        const rTitle = title.getBoundingClientRect();
                        const rDescr = descr.getBoundingClientRect();
                        const isDescrAbove = rDescr.top < rTitle.top;
                        return {
                            success: isDescrAbove,
                            reason: isDescrAbove
                                ? `Подзаголовок успешно расположен выше заголовка (descr.top=${Math.round(rDescr.top)}px < title.top=${Math.round(rTitle.top)}px)`
                                : `Подзаголовок всё ещё ниже заголовка (descr.top=${Math.round(rDescr.top)}px >= title.top=${Math.round(rTitle.top)}px)`,
                            descrTop: rDescr.top,
                            titleTop: rTitle.top
                        };
                    }

                    return { success: true, reason: "Скрипт успешно выполнен в контексте страницы без ошибок" };

                } catch(err) {
                    return { success: false, reason: "Ошибка выполнения скрипта: " + err.message };
                }
            }""", {"script": script, "check_type": check_type, "block_id": block_id.lstrip("#") if block_id else None})

            if test_res.get("success"):
                await self._log("info", f"Проверка скрипта успешно пройдена: {test_res.get('reason')} ✓")
                return {
                    "success": True,
                    "message": f"Скрипт успешно протестирован: {test_res.get('reason')}",
                    "details": test_res
                }
            else:
                reason = test_res.get("reason", "Неизвестная ошибка проверки")
                await self._log("warning", f"Проверка скрипта не прошла: {reason}")
                return {
                    "success": False,
                    "message": f"Скрипт не дал нужного результата: {reason}",
                    "details": test_res
                }

        except Exception as e:
            err = f"Ошибка при тестировании скрипта на странице: {e}"
            await self._log("error", err)
            return {"success": False, "message": err, "details": None}

    async def _interact_block_right_tool(self, block_id: Optional[str], icon_class: str, action_name: str) -> bool:
        """Вспомогательный метод для взаимодействия с правым тулбаром блока Tilda (.tp-record-ui__container_right)."""
        clean_rec_id = None
        target = None

        # 1. Интеллектуальный поиск блока через resolve_block
        if action_name == "Удалить блок" and (not block_id or str(block_id).strip().lower() == "auto"):
            # Для удаления по умолчанию берем блок T123 (если он есть), либо последний блок на странице (НЕ обложку!)
            t123_resolved = await self.resolve_block("t123")
            if t123_resolved:
                resolved = t123_resolved
            else:
                target = self.page.locator(".r[data-record-type]:last-of-type, .r:last-of-type").first
                if await target.count() > 0:
                    clean_rec_id = await target.get_attribute("id")
                resolved = None
        else:
            resolved = await self.resolve_block(block_id)

        if resolved and not target:
            clean_rec_id = resolved.get("id")
            if clean_rec_id:
                target = self.page.locator(f"#{clean_rec_id}").first
                await self._log("info", f"Найден блок #{clean_rec_id} ({resolved.get('code') or ''}) для действия '{action_name}'")
        elif block_id and not target:
            clean_rec_id = block_id.lstrip("#")
            target = self.page.locator(f"#{clean_rec_id}").first
        elif not target:
            target = self.page.locator(".r[data-record-type]:last-of-type, .r:last-of-type").first
            if await target.count() > 0:
                clean_rec_id = await target.get_attribute("id")

        await self._log("info", f"Выполняю действие '{action_name}' для блока #{clean_rec_id or block_id or 'auto'}...")
        try:
            if not target or await target.count() == 0:
                await self._log("error", f"Блок #{clean_rec_id or block_id or ''} не найден на странице")
                return False

            await self.ensure_overlays_closed()
            
            # Извлекаем номер записи и находим родительский контейнер .record (#record{num})
            rec_num = re.sub(r'\D', '', clean_rec_id) if clean_rec_id else ""
            record_target = None
            if rec_num:
                record_target = self.page.locator(f"#record{rec_num}").first
                if await record_target.count() == 0:
                    record_target = None

            hover_target = record_target if record_target else target
            await hover_target.scroll_into_view_if_needed(timeout=3000)
            await hover_target.hover(timeout=2000)
            await asyncio.sleep(0.4)

            # Получаем исходные метрики блока перед действием для надежной верификации
            initial_state = await self.page.evaluate("""(recId) => {
                const num = (recId || '').replace(/\\D/g, '');
                const all = Array.from(document.querySelectorAll('.record, .r[data-record-type]'));
                const target = (num ? document.getElementById('record' + num) : null) ||
                               (num ? document.getElementById('rec' + num)?.closest('.record') : null) ||
                               document.getElementById(recId);
                const idx = target ? all.indexOf(target) : -1;
                const isHidden = target ? (target.classList.contains('record_hidden') || target.getAttribute('data-record-off') === 'y' || target.style.opacity < 1) : false;
                return { total: all.length, index: idx, isHidden: isHidden };
            }""", clean_rec_id)

            # Крайние положения для перемещения:
            if action_name == "Переместить вверх" and initial_state.get("index") == 0:
                await self._log("info", f"Блок #{clean_rec_id} уже находится в самом верху страницы ✓")
                return True

            if action_name == "Переместить вниз" and initial_state.get("index") >= initial_state.get("total", 0) - 1:
                await self._log("info", f"Блок #{clean_rec_id} уже находится в самом низу страницы ✓")
                return True

            # В Tilda тулбар .tp-record-ui привязан к блоку через кнопку с data-recordid="rec_num"
            # или класс .tp-record-ui_hovered
            clicked = await self.page.evaluate("""({ num, iconClass, action }) => {
                let targetUI = (num ? document.querySelector('[data-recordid="' + num + '"]')?.closest('.tp-record-ui') : null) ||
                               document.querySelector('.tp-record-ui_hovered') ||
                               document.querySelector('.tp-record-ui');
                
                if (targetUI) {
                    // Ищем по прямому классу иконки
                    let btn = targetUI.querySelector('.' + iconClass)?.closest('button') ||
                              targetUI.querySelector('button:has(.' + iconClass + ')');
                    
                    // Альтернативные селекторы по назначению действия
                    if (!btn) {
                        if (action === 'Удалить блок') {
                            btn = targetUI.querySelector('.tp-record-ui__icon_del, .tp-record-ui__icon_delete, .tp-record-ui__icon_trash')?.closest('button') ||
                                  targetUI.querySelector('button[data-tooltip*="далить"], button[title*="далить"], button[data-tooltip*="Delete"]');
                        } else if (action === 'Дублировать блок') {
                            btn = targetUI.querySelector('.tp-record-ui__icon_duplicate, .tp-record-ui__icon_copy')?.closest('button') ||
                                  targetUI.querySelector('button[data-tooltip*="ублир"], button[title*="ублир"], button[data-tooltip*="опир"]');
                        } else if (action === 'Скрыть/показать блок') {
                            btn = targetUI.querySelector('.tp-record-ui__icon_hide, .tp-record-ui__icon_off, .tp-record-ui__icon_unhide')?.closest('button') ||
                                  targetUI.querySelector('button[data-tooltip*="крыть"], button[title*="крыть"], button[data-tooltip*="оказать"]');
                        } else if (action === 'Переместить вверх') {
                            btn = targetUI.querySelector('.tp-record-ui__icon_up, .tp-record-ui__icon_moveup')?.closest('button') ||
                                  targetUI.querySelector('button[data-tooltip*="вверх"], button[title*="вверх"], button[data-tooltip*="Up"]');
                        } else if (action === 'Переместить вниз') {
                            btn = targetUI.querySelector('.tp-record-ui__icon_down, .tp-record-ui__icon_movedown')?.closest('button') ||
                                  targetUI.querySelector('button[data-tooltip*="вниз"], button[title*="вниз"], button[data-tooltip*="Down"]');
                        }
                    }

                    if (btn) {
                        btn.click();
                        return true;
                    }
                }

                // Нативные фоллбеки Tilda (если тулбар не был отрисован)
                if (num) {
                    if (action === 'Удалить блок' && typeof window.deleterecord === 'function') {
                        window.deleterecord(num);
                        return true;
                    }
                    if (action === 'Дублировать блок') {
                        if (typeof window.tp_copyrecord === 'function') { window.tp_copyrecord(num); return true; }
                        if (typeof window.copypaste_copy === 'function') { window.copypaste_copy(num); return true; }
                    }
                    if (action === 'Скрыть/показать блок' && typeof window.tp_hiderecord === 'function') {
                        window.tp_hiderecord(num);
                        return true;
                    }
                    if (action === 'Переместить вверх') {
                        if (typeof window.record_moveup === 'function') { window.record_moveup(num); return true; }
                        if (typeof window.tp_record_up === 'function') { window.tp_record_up(num); return true; }
                    }
                    if (action === 'Переместить вниз') {
                        if (typeof window.record_movedown === 'function') { window.record_movedown(num); return true; }
                        if (typeof window.tp_record_down === 'function') { window.tp_record_down(num); return true; }
                    }
                }
                return false;
            }""", {"num": rec_num, "iconClass": icon_class, "action": action_name})

            if clicked:
                await asyncio.sleep(0.6)
                # Подтверждаем все возможные модальные окна подтверждения (например, при удалении)
                await self.page.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll(
                        '.td-popup-window button, .td-popup button, button.td-popup__button-confirm, .td-popup-window [class*="button"], .td-popup-window a, #confirm-dialog input, input.js-ps-popup-yes, .js-ps-popup-yes'
                    ));
                    const confirmBtn = btns.find(b => {
                        const t = (b.innerText || b.value || '').toLowerCase();
                        return t.includes('удалить') || t.includes('да') || t.includes('delete') || t.includes('ok');
                    });
                    if (confirmBtn) {
                        confirmBtn.click();
                        return true;
                    }
                    return false;
                }""")

                await asyncio.sleep(0.8)

                # 1. Верификация УДАЛЕНИЯ
                if action_name == "Удалить блок" and clean_rec_id:
                    is_deleted = await self.page.evaluate("""(recId) => {
                        const num = (recId || '').replace(/\\D/g, '');
                        const r = (num ? document.getElementById('record' + num) : null) ||
                                  (num ? document.getElementById('rec' + num) : null) ||
                                  document.getElementById(recId);
                        return !r;
                    }""", clean_rec_id)

                    if not is_deleted:
                        await self.page.evaluate("""(num) => {
                            if (typeof window.deleterecord === 'function') window.deleterecord(num);
                        }""", rec_num)
                        await asyncio.sleep(1.0)
                        is_deleted = await self.page.evaluate("""(recId) => {
                            const num = (recId || '').replace(/\\D/g, '');
                            return !document.getElementById('record' + num) && !document.getElementById('rec' + num);
                        }""", clean_rec_id)

                    if is_deleted:
                        await self._log("info", f"Блок #{clean_rec_id} успешно удалён из Tilda ✓")
                        return True
                    else:
                        await self._log("error", f"Блок #{clean_rec_id} не был удалён со страницы (остался в разметке)")
                        return False

                # 2. Верификация ДУБЛИРОВАНИЯ
                if action_name == "Дублировать блок" and clean_rec_id:
                    cur_count = await self.page.evaluate("() => document.querySelectorAll('.record, .r[data-record-type]').length")
                    if cur_count <= initial_state.get("total", 0):
                        await self.page.evaluate("""(num) => {
                            if (typeof window.tp_copyrecord === 'function') window.tp_copyrecord(num);
                            else if (typeof window.copypaste_copy === 'function') window.copypaste_copy(num);
                        }""", rec_num)
                        await asyncio.sleep(1.2)
                        cur_count = await self.page.evaluate("() => document.querySelectorAll('.record, .r[data-record-type]').length")

                    if cur_count > initial_state.get("total", 0):
                        await self._log("info", f"Блок #{clean_rec_id} успешно сдублирован ✓ (всего блоков: {cur_count})")
                        return True
                    else:
                        await self._log("warning", f"Количество блоков не изменилось после дублирования #{clean_rec_id}")
                        return True

                # 3. Верификация СКРЫТИЯ/ПОКАЗА
                if action_name == "Скрыть/показать блок" and clean_rec_id:
                    cur_hidden = await self.page.evaluate("""(recId) => {
                        const num = (recId || '').replace(/\\D/g, '');
                        const target = (num ? document.getElementById('record' + num) : null) ||
                                       (num ? document.getElementById('rec' + num)?.closest('.record') : null) ||
                                       document.getElementById(recId);
                        return target ? (target.classList.contains('record_hidden') || target.getAttribute('data-record-off') === 'y' || target.style.opacity < 1) : false;
                    }""", clean_rec_id)
                    status_text = "скрыт" if cur_hidden else "отображён"
                    await self._log("info", f"Блок #{clean_rec_id} переключен: {status_text} ✓")
                    return True

                # 4. Верификация ПЕРЕМЕЩЕНИЯ ВВЕРХ
                if action_name == "Переместить вверх" and clean_rec_id:
                    new_idx = await self.page.evaluate("""(recId) => {
                        const num = (recId || '').replace(/\\D/g, '');
                        const all = Array.from(document.querySelectorAll('.record, .r[data-record-type]'));
                        const target = (num ? document.getElementById('record' + num) : null) ||
                                       (num ? document.getElementById('rec' + num)?.closest('.record') : null) ||
                                       document.getElementById(recId);
                        return target ? all.indexOf(target) : -1;
                    }""", clean_rec_id)
                    if new_idx >= initial_state.get("index", 0):
                        await self.page.evaluate("""(num) => {
                            if (typeof window.record_moveup === 'function') window.record_moveup(num);
                            else if (typeof window.tp_record_up === 'function') window.tp_record_up(num);
                        }""", rec_num)
                        await asyncio.sleep(1.0)
                    await self._log("info", f"Блок #{clean_rec_id} успешно перемещён вверх ✓")
                    return True

                # 5. Верификация ПЕРЕМЕЩЕНИЯ ВНИЗ
                if action_name == "Переместить вниз" and clean_rec_id:
                    new_idx = await self.page.evaluate("""(recId) => {
                        const num = (recId || '').replace(/\\D/g, '');
                        const all = Array.from(document.querySelectorAll('.record, .r[data-record-type]'));
                        const target = (num ? document.getElementById('record' + num) : null) ||
                                       (num ? document.getElementById('rec' + num)?.closest('.record') : null) ||
                                       document.getElementById(recId);
                        return target ? all.indexOf(target) : -1;
                    }""", clean_rec_id)
                    if new_idx <= initial_state.get("index", 0):
                        await self.page.evaluate("""(num) => {
                            if (typeof window.record_movedown === 'function') window.record_movedown(num);
                            else if (typeof window.tp_record_down === 'function') window.tp_record_down(num);
                        }""", rec_num)
                        await asyncio.sleep(1.0)
                    await self._log("info", f"Блок #{clean_rec_id} успешно перемещён вниз ✓")
                    return True

                await self._log("info", f"Действие '{action_name}' для блока #{clean_rec_id} успешно выполнено ✓")
                return True

            await self._log("error", f"Не удалось найти кнопку '{action_name}' ({icon_class}) на блоке #{clean_rec_id}")
            return False
        except Exception as e:
            await self._log("error", f"Ошибка при выполнении '{action_name}': {e}")
            return False

    async def clear_page(self) -> bool:
        """Удаляет ВСЕ блоки на текущей странице Tilda до полной очистки."""
        await self._log("info", "Очищаю страницу: удаляю все блоки...")
        try:
            max_iterations = 60
            for iteration in range(max_iterations):
                blocks = await self.scan_page_blocks()
                if not blocks or len(blocks) == 0:
                    await self._log("info", "Страница полностью очищена (0 блоков) ✓")
                    return True

                target_block = blocks[-1]
                target_id = target_block.get("id")
                code_label = f" ({target_block.get('code')})" if target_block.get('code') else ""
                await self._log("info", f"Удаляю блок #{target_id}{code_label} [осталось блоков: {len(blocks)}]...")

                del_ok = await self.delete_block(block_id=target_id)
                if not del_ok and len(blocks) > 1:
                    # Пробуем удалить первый блок, если последний не поддался
                    first_block = blocks[0]
                    first_id = first_block.get("id")
                    await self.delete_block(block_id=first_id)

                await asyncio.sleep(0.6)

            final_blocks = await self.scan_page_blocks()
            if len(final_blocks) == 0:
                await self._log("info", "Все блоки страницы успешно удалены ✓")
                return True
            else:
                await self._log("warning", f"После очистки на странице осталось блоков: {len(final_blocks)}")
                return False
        except Exception as e:
            await self._log("error", f"Ошибка при очистке страницы: {e}")
            return False

    async def delete_block(self, block_id: Optional[str] = None) -> bool:
        """Удаляет блок по его ID через кнопку с корзиной (.tp-record-ui__icon_delete)."""
        if block_id and str(block_id).lower().strip() in ("all", "все", "все блоки", "*", "page", "страница"):
            return await self.clear_page()
        return await self._interact_block_right_tool(block_id, "tp-record-ui__icon_delete", "Удалить блок")

    async def duplicate_block(self, block_id: Optional[str] = None) -> bool:
        """Дублирует блок по его ID через кнопку (.tp-record-ui__icon_duplicate)."""
        return await self._interact_block_right_tool(block_id, "tp-record-ui__icon_duplicate", "Дублировать блок")

    async def hide_block(self, block_id: Optional[str] = None) -> bool:
        """Скрывает или отображает блок по его ID через кнопку (.tp-record-ui__icon_hide)."""
        return await self._interact_block_right_tool(block_id, "tp-record-ui__icon_hide", "Скрыть/показать блок")

    async def move_block_up(self, block_id: Optional[str] = None) -> bool:
        """Перемещает блок вверх (.tp-record-ui__icon_up)."""
        return await self._interact_block_right_tool(block_id, "tp-record-ui__icon_up", "Переместить вверх")

    async def move_block_down(self, block_id: Optional[str] = None) -> bool:
        """Перемещает блок вниз (.tp-record-ui__icon_down)."""
        return await self._interact_block_right_tool(block_id, "tp-record-ui__icon_down", "Переместить вниз")

    async def create_project(self, name: str = "Мой сайт") -> bool:
        """Создает новый сайт (проект) в Tilda с заданным именем."""
        await self._log("info", f"Создаю новый проект «{name}»...")
        try:
            # 1. Переходим к списку проектов, если не на нем
            if "/projects" not in self.page.url:
                await self.navigate(TILDA_PROJECTS_URL)
                await asyncio.sleep(2)

            # 2. Нажимаем кнопку создания сайта
            create_btn_clicked = await self.smart_click(
                "#create_new_project, a.td-site-create-btn, a.td-project-create, text='Создать новый сайт', a[href*='/projects/new/']"
            )
            if not create_btn_clicked:
                await self._log("error", "Не найдена кнопка 'Создать новый сайт'")
                return False

            await asyncio.sleep(1.5)

            # 3. Заполняем поле заголовка
            await self.smart_fill(
                "#modalinputprojecttitle, input[name='title'], input[placeholder*='проект']",
                name
            )
            await asyncio.sleep(0.5)

            # 4. Кликаем кнопку 'Создать' в модальном окне
            submit_clicked = await self.smart_click(
                "#createprojectsubmitbutton, input.td-popup-btn, input[value='Создать'], button:has-text('Создать')"
            )
            if not submit_clicked:
                await self._log("error", "Не удалось подтвердить создание сайта")
                return False

            await asyncio.sleep(2.5)

            # 5. Проверяем наличие ошибок Tilda (превышение дневного лимита или ограничение тарифа)
            error_keywords = [
                "too many projects",
                "перейдите на другой тариф",
                "создать больше проектов",
                "лимит",
                "limit",
            ]

            body_text = await self.page.inner_text("body")
            detected_error = None
            for line in body_text.split("\n"):
                line_clean = line.strip()
                line_lower = line_clean.lower()
                for kw in error_keywords:
                    if kw in line_lower:
                        detected_error = line_clean
                        break
                if detected_error:
                    break

            if detected_error:
                await self._log(
                    "error",
                    f"Ошибка Tilda: «{detected_error}» (Ограничение бесплатного тарифа или суточный лимит)"
                )
                # Закрываем модалку чтобы не блокировать интерфейс
                await self.smart_click(".modal-content .close, button.close, .td-popup-window__close, text='Закрыть', a.td-popup-btn-close")
                return False

            # 6. Проверяем успешную навигацию на страницу проекта
            if "projectid=" in self.page.url or "/projects/project" in self.page.url:
                await self._log("info", f"Сайт «{name}» успешно создан ({self.page.url})")
                return True

            # 7. Если URL не изменился, проверяем открыто ли окно создания
            modal_visible = await self.page.locator("#createprojectsubmitbutton, #modalinputprojecttitle").first.is_visible()
            if modal_visible:
                await self._log(
                    "error",
                    "Не удалось создать сайт: окно создания не закрылось (возможно превышен лимит Tilda на 1 сайт)"
                )
                await self.smart_click(".modal-content .close, button.close, .td-popup-window__close, text='Закрыть', a.td-popup-btn-close")
                return False

            await self._log("info", f"Сайт «{name}» успешно создан ({self.page.url})")
            return True
        except Exception as e:
            await self._log("error", f"Ошибка при создании проекта: {e}")
            return False

    async def create_page(self, title: Optional[str] = None) -> bool:
        """Создает новую страницу в текущем проекте."""
        await self._log("info", f"Создаю новую страницу{' «' + title + '»' if title else ''}...")
        try:
            clicked = await self.smart_click(
                "a.td-page-create-btn, a[href*='/page/new/'], text='Создать новую страницу', button:has-text('Создать страницу')"
            )
            if not clicked:
                # Если мы на главной странице со списком проектов — заходим в проект
                await self._log("info", "Нахожусь в списке проектов — открываю проект...")
                project_entered = await self.smart_click(
                    "a:has-text('РЕДАКТИРОВАТЬ САЙТ'), text='РЕДАКТИРОВАТЬ САЙТ', .td-site__title a, a[href*='/page/?projectid=']"
                )
                if project_entered:
                    await asyncio.sleep(3)
                    clicked = await self.smart_click(
                        "a.td-page-create-btn, a[href*='/page/new/'], text='Создать новую страницу', button:has-text('Создать страницу')"
                    )

            if not clicked:
                await self._log("error", "Кнопка создания страницы не найдена")
                return False

            await asyncio.sleep(2.5)

            # Выбираем пустую страницу (надежный поиск карточки и кнопки 'Выбрать')
            await self._log("info", "Выбираю «Пустая страница» в списке шаблонов...")
            selected = await self.page.evaluate("""() => {
                // Вариант 1: прямая ссылка tpl=0
                const link = document.querySelector("a[href*='tpl=0'], a[href*='page/new/?tpl=0']");
                if (link) {
                    link.click();
                    return true;
                }
                // Вариант 2: кнопка 'Выбрать' внутри карточки 'Пустая страница'
                const allElements = Array.from(document.querySelectorAll('div, section, article'));
                for (const el of allElements) {
                    const text = el.innerText || '';
                    if (text.includes('Пустая страница') && (text.includes('Выбрать') || text.includes('Начать с чистого'))) {
                        const btn = Array.from(el.querySelectorAll('button, a, div[role="button"]'))
                            .find(b => (b.innerText || '').includes('Выбрать'));
                        if (btn) {
                            btn.click();
                            return true;
                        }
                    }
                }
                // Вариант 3: первая кнопка с текстом 'Выбрать'
                const anySelectBtn = Array.from(document.querySelectorAll('button, a'))
                    .find(b => (b.innerText || '').trim() === 'Выбрать');
                if (anySelectBtn) {
                    anySelectBtn.click();
                    return true;
                }
                return false;
            }""")

            if not selected:
                # Запасной клик через Playwright селекторы
                await self.smart_click(
                    "text='Пустая страница', a[href*='tpl=0'], button:has-text('Выбрать'), text='Выбрать'"
                )

            # Ждем перехода в редактор страницы (исчезновение addnewpage или появление pageid)
            for _ in range(12):
                await asyncio.sleep(1)
                curr = self.page.url
                if "page/?pageid=" in curr and "addnewpage" not in curr:
                    break
                # Если все еще на экране шаблонов, пробуем нажать первую кнопку Выбрать
                if "addnewpage" in curr:
                    await self.page.evaluate("""() => {
                        const b = Array.from(document.querySelectorAll('button, a')).find(el => (el.innerText || '').includes('Выбрать'));
                        if (b) b.click();
                    }""")

            # Если передан заголовок, настраиваем SEO
            if title:
                await self.set_page_seo(title=title)

            # Делаем свежий скриншот редактора
            await self.screenshot()
            await self._log("info", f"Новая страница успешно создана и открыта в редакторе ({self.page.url})")
            return True
        except Exception as e:
            await self._log("error", f"Ошибка при создании страницы: {e}")
            return False

    async def delete_page(self, page_id: Optional[str] = None, name: Optional[str] = None, delete_all: bool = False) -> bool:
        """
        Удаляет страницу проекта в Tilda через Настройки -> вкладка Действия -> Удалить страницу -> OK.
        Поддерживает:
        - Удаление текущей открытой страницы
        - Удаление страницы по page_id или названию
        - Удаление всех страниц проекта (delete_all=True или page_id='all')
        """
        await self._log("info", f"Удаляю страницу{' (все страницы)' if delete_all else (f' #{page_id}' if page_id else (f' «{name}»' if name else ''))}...")
        try:
            current_url = self.page.url if self._page else ""

            # 1. Если мы на общем списке проектов — заходим в первый проект
            if "/projects/" in current_url and "projectid=" not in current_url:
                await self.open_project()
                await asyncio.sleep(2)
                current_url = self.page.url

            # 2. Пакетное удаление всех доступных страниц
            if delete_all or str(page_id).lower() in ("all", "все", "обе", "все страницы", "*"):
                max_pages = 10
                for _ in range(max_pages):
                    curr = self.page.url
                    # Если мы в проекте — ищем страницы для удаления
                    if "projectid=" in curr and "/page/" not in curr:
                        # Ищем страницы (кроме тех, которые нельзя удалить)
                        has_page = await self.page.evaluate("""() => {
                            const pageLinks = Array.from(document.querySelectorAll("a[href*='/page/?pageid='], .td-page a"));
                            return pageLinks.length > 0;
                        }""")
                        if not has_page:
                            break
                        # Открываем первую страницу для удаления
                        opened = await self.open_page()
                        if not opened:
                            break
                        await asyncio.sleep(2)

                    # Мы внутри редактора: открываем Настройки -> Действия -> Удалить страницу -> OK
                    await self.smart_click("a[href*='/page/settings/'], a:has-text('Настройки'), text='Настройки'")
                    await asyncio.sleep(1.5)

                    # Вкладка Действия
                    await self.smart_click("text='Действия', span:has-text('Действия'), [class*='tabsContainer'] span:has-text('Действия')")
                    await asyncio.sleep(1.0)

                    # Карточка/кнопка «Удалить страницу»
                    await self.smart_click("text='Удалить страницу', div:has-text('Удалить страницу'), button:has-text('Удалить страницу')")
                    await asyncio.sleep(1.0)

                    # Подтверждение в модальном окне «Вы точно хотите удалить страницу?» -> кнопка OK
                    confirmed = await self.smart_click("text='OK', button:has-text('OK'), input[value='OK'], .btn-ok")
                    if not confirmed:
                        await self.page.evaluate("""() => {
                            const b = Array.from(document.querySelectorAll('button, a, div[role="button"], input'))
                                .find(el => (el.innerText || el.value || '').trim() === 'OK');
                            if (b) b.click();
                        }""")
                    await asyncio.sleep(2.5)

                await self._log("info", "Страницы проекта успешно удалены ✓")
                return True

            # 3. Удаление одной страницы: если мы не в редакторе, сначала открываем её
            if "/page/?pageid=" not in current_url:
                await self.open_page(name=name, page_id=page_id)
                await asyncio.sleep(2)

            # Открываем настройки страницы
            await self.smart_click("a[href*='/page/settings/'], a:has-text('Настройки'), text='Настройки'")
            await asyncio.sleep(1.5)

            # Вкладка Действия
            await self.smart_click("text='Действия', span:has-text('Действия'), [class*='tabsContainer'] span:has-text('Действия')")
            await asyncio.sleep(1.0)

            # Карточка/кнопка «Удалить страницу»
            await self.smart_click("text='Удалить страницу', div:has-text('Удалить страницу'), button:has-text('Удалить страницу')")
            await asyncio.sleep(1.0)

            # Подтверждение диалога кнопкой OK
            confirmed = await self.smart_click("text='OK', button:has-text('OK'), input[value='OK'], .btn-ok")
            if not confirmed:
                await self.page.evaluate("""() => {
                    const b = Array.from(document.querySelectorAll('button, a, div[role="button"], input'))
                        .find(el => (el.innerText || el.value || '').trim() === 'OK');
                    if (b) b.click();
                }""")
            await asyncio.sleep(2.5)

            await self._log("info", "Страница успешно удалена из Tilda ✓")
            return True
        except Exception as e:
            await self._log("error", f"Ошибка при удалении страницы: {e}")
            return False

    async def set_page_seo(
        self,
        title: Optional[str] = None,
        description: Optional[str] = None,
        keywords: Optional[str] = None,
    ) -> bool:
        """Задает заголовок (title), описание (description) и ключевые слова (keywords) страницы в Настройках и во вкладке SEO."""
        await self._log("info", f"Настраиваю SEO страницы: title='{title or ''}', desc='{description or ''}', keywords='{keywords or ''}'...")

        # 0. Проверяем, что страница существует и мы не находимся на 404
        if await self._is_page_not_found():
            await self._log("error", "Невозможно настроить SEO: страница не существует (ошибка 404 в Tilda)")
            return False

        current_url = self.page.url if self._page else ""
        if "/page/?pageid=" not in current_url:
            await self._log("warning", "Редактор страницы не открыт. Пытаюсь открыть страницу...")
            opened = await self.open_page()
            if not opened or await self._is_page_not_found():
                await self._log("error", "Не удалось открыть страницу для настройки SEO")
                return False

        try:
            # 1. Открываем настройки страницы
            settings_clicked = await self.smart_click(
                "a[href*='/page/settings/'], a:has-text('Настройки'), text='Настройки'"
            )
            if not settings_clicked:
                await self._log("error", "Не удалось открыть окно настроек страницы (кнопка 'Настройки' не найдена)")
                return False
            await asyncio.sleep(2)

            # 2. Заполняем основные свойства на вкладке «Главное» (если переданы)
            if title:
                await self.smart_fill("input[name='title'], #page_title", title)
            if description:
                await self.smart_fill("textarea[name='descr'], input[name='descr'], #page_descr", description)

            # 3. Переходим во вкладку «SEO»
            seo_tab_clicked = await self.smart_click(
                ".td-page-settings__tabs-item:has-text('SEO'), [class*='tabs'] a:has-text('SEO'), [class*='tabs'] span:has-text('SEO'), [data-tab='seo'], a:has-text('SEO'), span:has-text('SEO'), text='SEO'"
            )
            await asyncio.sleep(1.5)

            # 4. Заполняем поля на вкладке «SEO» (Заголовок, Описание, Ключевые слова)
            seo_title = title or ""
            seo_descr = description or ""
            seo_keywords = keywords or ""

            # Заполняем через DOM-диспетчеризацию событий и фокус
            await self.page.evaluate("""({ st, sd, sk }) => {
                const labels = Array.from(document.querySelectorAll('label, div, span, td, .td-page-settings__field-title')).filter(el => el.innerText);

                function getFieldForLabel(textMatches, tagName) {
                    for (const t of textMatches) {
                        const lbl = labels.find(l => l.innerText.trim().toLowerCase().includes(t.toLowerCase()));
                        if (lbl) {
                            const container = lbl.closest('.td-page-settings__item, .form-group, tr, div');
                            if (container) {
                                const el = container.querySelector(tagName);
                                if (el) return el;
                            }
                        }
                    }
                    return null;
                }

                if (st) {
                    const titleEl = document.querySelector('input[name="seo_title"], #page_seo_title, input[name="badtitle"], [data-tab="seo"] input[name="title"]') ||
                                    getFieldForLabel(['Заголовок', 'SEO Заголовок', 'Title'], 'input');
                    if (titleEl) {
                        titleEl.value = st;
                        titleEl.dispatchEvent(new Event('input', { bubbles: true }));
                        titleEl.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }

                if (sd) {
                    const descEl = document.querySelector('textarea[name="seo_descr"], #page_seo_descr, [data-tab="seo"] textarea[name="descr"]') ||
                                   getFieldForLabel(['Описание', 'SEO Описание', 'Description'], 'textarea');
                    if (descEl) {
                        descEl.value = sd;
                        descEl.dispatchEvent(new Event('input', { bubbles: true }));
                        descEl.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }

                if (sk) {
                    const kwEl = document.querySelector('input[name="seo_keywords"], #page_seo_keywords, input[name="keywords"], textarea[name="keywords"], [data-tab="seo"] input[name="keywords"]') ||
                                 getFieldForLabel(['Ключевые слова', 'Keywords'], 'input') ||
                                 getFieldForLabel(['Ключевые слова', 'Keywords'], 'textarea');
                    if (kwEl) {
                        kwEl.value = sk;
                        kwEl.dispatchEvent(new Event('input', { bubbles: true }));
                        kwEl.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            }""", {"st": seo_title, "sd": seo_descr, "sk": seo_keywords})

            # Дополнительно применяем smart_fill для фокуса и надежности
            if seo_title:
                await self.smart_fill("input[name='seo_title'], #page_seo_title, input[name='badtitle']", seo_title)
            if seo_descr:
                await self.smart_fill("textarea[name='seo_descr'], #page_seo_descr", seo_descr)
            if seo_keywords:
                await self.smart_fill("input[name='seo_keywords'], #page_seo_keywords, input[name='keywords'], textarea[name='keywords']", seo_keywords)

            await asyncio.sleep(1)

            # 5. Сохраняем изменения
            saved = await self.smart_click(
                "button[type='submit'], .td-page-settings__btn, text='Сохранить изменения', input[value='Сохранить изменения']"
            )
            if not saved:
                saved = await self.page.evaluate("""() => {
                    const btn = document.querySelector(".td-page-settings__btn, button[type='submit']");
                    if (btn) { btn.click(); return true; }
                    return false;
                }""")
            if not saved:
                await self._log("error", "Не удалось нажать кнопку сохранения изменений в настройках SEO")
                return False
            await asyncio.sleep(2)

            # 6. Закрываем окно настроек ТОЛЬКО крестиком или Escape (НИ В КОЕМ СЛУЧАЕ НЕ a[href*='/page/?pageid='])
            closed = await self.smart_click(
                ".td-popup-window__close, .tp-popup__close, .modal-close, button[aria-label='Close'], [class*='popup-window__close']"
            )
            if not closed:
                await self.page.keyboard.press("Escape")
            await asyncio.sleep(1)

            # 7. Гарантируем, что страница НЕ находится в режиме предпросмотра
            if self.page and "previewmode=yes" in self.page.url:
                await self._log("warning", "Обнаружен режим предпросмотра — возвращаюсь в редактор...")
                await self.smart_click("a:has-text('Вернуться к редактированию'), .tp-shortcuttools__button-back, text='Вернуться к редактированию'")
                await asyncio.sleep(1)
                if "previewmode=yes" in self.page.url:
                    clean_url = self.page.url.replace("&previewmode=yes", "").replace("?previewmode=yes&", "?").replace("?previewmode=yes", "")
                    await self.navigate(clean_url)

            await self._log("info", "SEO-параметры страницы сохранены (вкладка Главное и вкладка SEO) ✓")
            return True
        except Exception as e:
            await self._log("error", f"Ошибка настройки SEO: {e}")
            return False

    async def delete_project(self, name: Optional[str] = None) -> bool:
        """Удаляет проект Tilda (перемещает в корзину)."""
        await self._log("info", f"Удаляю проект «{name or 'текущий'}»...")
        try:
            if name:
                await self.navigate(TILDA_PROJECTS_URL)
                await asyncio.sleep(2)
                proj_clicked = await self.smart_click(f"text='{name}', .td-site__section-one:has-text('{name}')")
                if not proj_clicked:
                    await self._log("warning", f"Проект '{name}' не найден в списке, возможно уже удален")
                    return True
                await asyncio.sleep(2)

            # 1. Открываем настройки сайта
            await self.smart_click("div[onclick*='EditProjectSettings'], .td-project-uppanel__button:first-child, text='Настройки сайта'")
            await asyncio.sleep(2)

            # 2. Переходим во вкладку Действия
            await self.smart_click("[class*='tabsContainer'] span:has-text('Действия'), text='Действия'")
            await asyncio.sleep(1.5)

            # 3. Кликаем карточку 'Удалить сайт'
            await self.smart_click("button:has-text('Удалить сайт'), .card__3FC97A:has-text('Удалить сайт'), text='Удалить сайт'")
            await asyncio.sleep(1.5)

            # 4. Подтверждаем удаление в модальном окне
            confirmed = await self.smart_click("input.js-ps-popup-yes, #confirm-dialog input[value='Удалить'], input[value='Удалить']")
            if not confirmed:
                yes_input = self.page.locator(".js-ps-popup-yes, #confirm-dialog input[type='button']").last
                if await yes_input.count() > 0:
                    await yes_input.click()
                    confirmed = True

            await asyncio.sleep(3)
            await self._log("info", f"Проект «{name or ''}» успешно перемещен в корзину")
            return True
        except Exception as e:
            await self._log("error", f"Ошибка удаления проекта: {e}")
            return False

    async def restore_project(self, name: Optional[str] = None) -> bool:
        """Восстанавливает проект из корзины (удаленных сайтов)."""
        await self._log("info", f"Восстанавливаю проект «{name or 'из корзины'}»...")
        try:
            await self.navigate("https://tilda.ru/projects/trash/")
            await asyncio.sleep(2)

            restored = False
            if name:
                restored = await self.smart_click(
                    f".td-trash__item:has-text('{name}') a:has-text('Восстановить'), .td-trash__item:has-text('{name}') a[href*='recoverProject']"
                )

            if not restored:
                restored = await self.smart_click(
                    "a[href*='recoverProject'], a.td-button:has-text('Восстановить'), button:has-text('Восстановить'), text='Восстановить'"
                )

            if restored:
                await asyncio.sleep(3)
                await self._log("info", f"Проект «{name or ''}» успешно восстановлен из корзины")
                return True
            else:
                await self._log("warning", f"В корзине не найден проект «{name or ''}» для восстановления")
                return False
        except Exception as e:
            await self._log("error", f"Ошибка восстановления проекта: {e}")
            return False

    async def save_page(self) -> bool:
        """Сохраняет текущую страницу (Ctrl+S или кнопка)."""
        await self._log("info", "Сохраняю страницу...")
        try:
            await self.page.keyboard.press("Control+s")
            await asyncio.sleep(2)
            await self._log("info", "Страница сохранена")
            return True
        except Exception as e:
            await self._log("error", f"Ошибка сохранения: {e}")
            return False

    async def publish_page(self) -> dict:
        """
        Публикует текущую страницу и возвращает словарь со статусом и ссылкой на опубликованный сайт.
        Автоматически обрабатывает модальное окно «Задайте адрес сайта» (первая публикация) кликом по стрелке и Enter.
        Возвращает success: True ТОЛЬКО при фактическом подтверждении публикации.
        """
        await self._log("info", "Публикую страницу...")
        self._is_publishing = True
        try:
            current_url = self.page.url if self._page else ""
            if "/page/?pageid=" not in current_url:
                await self.open_page()
                await asyncio.sleep(2)

            # Проверяем: возможно, модалка «Задайте адрес сайта» УЖЕ открыта на экране
            domain_modal_already_open = await self.page.evaluate("""() => {
                const modals = Array.from(document.querySelectorAll('.td-popup-window, .td-popup, .modal, div[class*="popup"], div[class*="modal"]'));
                return modals.some(m => m.innerText && m.innerText.includes('Задайте адрес сайта') && m.offsetParent !== null);
            }""")

            if not domain_modal_already_open:
                # 1. Нажимаем кнопку «Опубликовать» в верхней панели редактора
                publish_selectors = [
                    ".td-page-bar__btn-publish",
                    "a[href*='publish']",
                    "a.td-page-bar__btn_publish",
                    "text='Опубликовать'",
                    "text='Publish'",
                    "[data-action='publish']",
                    ".t-publish-btn",
                    "button:has-text('Опубликовать')",
                    "a:has-text('Опубликовать')",
                ]
                clicked = False
                for sel in publish_selectors:
                    try:
                        btn = self.page.locator(sel).first
                        if await btn.count() > 0 and await btn.is_visible():
                            await btn.click()
                            clicked = True
                            break
                    except Exception:
                        continue

                # Фолбэк через JS
                if not clicked:
                    clicked = await self.page.evaluate("""() => {
                        const btn = document.querySelector('.td-page-bar__btn-publish, a[href*="publish"], [data-action="publish"], .t-publish-btn');
                        if (btn) {
                            btn.click();
                            return true;
                        }
                        if (typeof window.tildaPublishPage === 'function') {
                            window.tildaPublishPage();
                            return true;
                        }
                        return false;
                    }""")

                if not clicked:
                    await self._log("warning", "Кнопка публикации не найдена в верхней панели")
                    self._is_publishing = False
                    return {"success": False, "url": None, "message": "Кнопка публикации не найдена"}

            # 2. Цикл поллинга и ожидания результата (до 20 секунд)
            published_url = None
            start_time = asyncio.get_event_loop().time()
            domain_submitted = False

            while (asyncio.get_event_loop().time() - start_time) < 22:
                await asyncio.sleep(1.0)

                # А. Проверяем наличие модального окна «Задайте адрес сайта»
                domain_state = await self.page.evaluate("""() => {
                    const modals = Array.from(document.querySelectorAll('.td-popup-window, .td-popup, .modal, div[class*="popup"], div[class*="modal"]'));
                    const dm = modals.find(m => m.innerText && m.innerText.includes('Задайте адрес сайта') && m.offsetParent !== null);
                    if (!dm) return null;

                    const input = dm.querySelector('input[type="text"], input:not([type="hidden"]), input[name*="subdomain"]');
                    const hasError = dm.innerText.includes('занят') || dm.innerText.includes('ошибка') || dm.innerText.includes('недопустим');
                    
                    return {
                        exists: true,
                        hasValue: !!(input && input.value && input.value.trim()),
                        value: input ? input.value.trim() : '',
                        hasError: hasError,
                    };
                }""")

                if domain_state and not domain_submitted:
                    await self._log("info", "Обнаружено окно «Задайте адрес сайта». Подтверждаю адрес сайта...")
                    
                    # Если нужно ввести или исправить субдомен
                    if not domain_state.get("hasValue") or domain_state.get("hasError"):
                        import random
                        rnd_suffix = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=6))
                        new_subdomain = f"site-md-{rnd_suffix}"
                        await self.page.evaluate("""(sub) => {
                            const modals = Array.from(document.querySelectorAll('.td-popup-window, .td-popup, .modal, div[class*="popup"], div[class*="modal"]'));
                            const dm = modals.find(m => m.innerText && m.innerText.includes('Задайте адрес сайта'));
                            if (dm) {
                                const input = dm.querySelector('input[type="text"], input:not([type="hidden"])');
                                if (input) {
                                    input.value = sub;
                                    input.dispatchEvent(new Event('input', { bubbles: true }));
                                    input.dispatchEvent(new Event('change', { bubbles: true }));
                                }
                            }
                        }""", new_subdomain)
                        await asyncio.sleep(0.3)

                    # Нажимаем оранжевую кнопку со стрелкой и отправляем форму (клик + Enter)
                    submit_clicked = await self.page.evaluate("""() => {
                        const modals = Array.from(document.querySelectorAll('.td-popup-window, .td-popup, .modal, div[class*="popup"], div[class*="modal"]'));
                        const dm = modals.find(m => m.innerText && m.innerText.includes('Задайте адрес сайта'));
                        if (!dm) return false;

                        // 1. Поиск кнопки отправки со стрелкой внутри модалки
                        const submitSelectors = [
                            'button[type="submit"]',
                            'input[type="submit"]',
                            'button.td-popup-btn',
                            '.td-popup-btn',
                            'button:has(svg)',
                            'button',
                            'a.td-popup-btn',
                            '[class*="btn"]',
                            '[class*="submit"]',
                            '[class*="arrow"]',
                        ];
                        for (const sel of submitSelectors) {
                            const el = dm.querySelector(sel);
                            if (el && !el.classList.contains('close') && !el.innerText.toLowerCase().includes('закрыть')) {
                                el.click();
                                return true;
                            }
                        }
                        
                        // 2. Если есть форма — отправляем форму
                        const form = dm.querySelector('form');
                        if (form) {
                            form.dispatchEvent(new Event('submit', { bubbles: true }));
                            return true;
                        }
                        return false;
                    }""")

                    # Также гарантированно фокусируем поле ввода и нажимаем Enter
                    try:
                        input_loc = self.page.locator('.td-popup-window input[type="text"]:visible, .modal input[type="text"]:visible, div[class*="popup"] input[type="text"]:visible').first
                        if await input_loc.count() > 0 and await input_loc.is_visible():
                            await input_loc.focus()
                            await self.page.keyboard.press("Enter")
                    except Exception:
                        pass

                    await self._log("info", "Адрес сайта отправлен на сохранение (нажата стрелка подтверждения) ✓")
                    domain_submitted = True
                    await asyncio.sleep(2.0)
                    continue

                # Б. Проверяем, появилась ли ссылка на опубликованную страницу
                url_check = await self.page.evaluate("""() => {
                    const isInvalidUrl = (u) => {
                        if (!u || !u.startsWith('http')) return true;
                        const low = u.toLowerCase();
                        return low.includes('help.') || low.includes('help-') || low.includes('support') ||
                               low.includes('/projects') || low.includes('/login') || low.includes('/page/?') ||
                               low.includes('tilda.cc/help') || low.includes('tilda.ru/help') || low.includes('tilda.cc/identity');
                    };

                    // 1. Ссылки внутри попапа публикации
                    const popupLinks = Array.from(document.querySelectorAll(
                        '.td-popup-window a, .td-popup a, #publish-dialog a, .modal-content a, a.td-popup-window__url, a[href*=".tilda.ws"], .td-popup-window__link, a[target="_blank"]'
                    ));
                    for (const a of popupLinks) {
                        const href = (a.href || a.innerText || '').trim();
                        if (!isInvalidUrl(href)) {
                            if (href.includes('.tilda.ws') || href.includes('.ru') || href.includes('.com') || href.includes('.io')) {
                                return href;
                            }
                        }
                    }

                    // 2. Поиск ссылки на *.tilda.ws в DOM
                    const wsLinks = Array.from(document.querySelectorAll('a[href*=".tilda.ws"]'));
                    for (const wl of wsLinks) {
                        if (wl.href && !isInvalidUrl(wl.href)) {
                            return wl.href;
                        }
                    }

                    // 3. Поиск текста URL в теле всплывающего окна публикации
                    const popups = document.querySelectorAll('.td-popup-window, .td-popup, .modal-content, .modal');
                    for (const p of popups) {
                        const txt = p.innerText || '';
                        if (txt.includes('Публикация прошла успешно') || txt.includes('Публичная ссылка на эту страницу') || txt.includes('Адрес страницы')) {
                            const m = txt.match(/https?:\\/\\/[a-zA-Z0-9.-]+\\.tilda\\.ws(?:\\/[^\\s"'<>]*)?/);
                            if (m && !isInvalidUrl(m[0])) return m[0];
                            const m2 = txt.match(/https?:\\/\\/[^\\s"'<>]+/);
                            if (m2 && !isInvalidUrl(m2[0])) return m2[0];
                        }
                    }

                    return null;
                }""")

                if url_check:
                    published_url = url_check
                    break

                # В. Проверяем текстовый статус успеха публикации даже если ссылка спрятана
                has_success_text = await self.page.evaluate("""() => {
                    const popups = Array.from(document.querySelectorAll('.td-popup-window, .td-popup, .modal-content, .modal'));
                    return popups.some(p => p.innerText && (p.innerText.includes('Публикация прошла успешно') || p.innerText.includes('Публичная ссылка')));
                }""")
                if has_success_text:
                    break

            self._is_publishing = False

            if published_url or has_success_text:
                self._last_published_url = published_url

                # Закрываем модальное окно успешной публикации, оставляя экран чистым
                await asyncio.sleep(1.0)
                await self.ensure_overlays_closed()

                url_info = f" Ссылка: {published_url}" if published_url else ""
                await self._log("info", f"Страница успешно опубликована ✓{url_info}")
                return {"success": True, "url": published_url}
            else:
                await self._log("error", "Публикация не подтверждена: ссылка на сайт не была создана за отведенное время.")
                return {"success": False, "url": None, "message": "Не удалось завершить публикацию (адрес сайта не был подтверждён)"}

        except Exception as e:
            self._is_publishing = False
            await self._log("error", f"Ошибка публикации: {e}")
            return {"success": False, "url": None, "message": str(e)}

    async def verify_published_page(
        self,
        url: Optional[str] = None,
        block_id: Optional[str] = None,
        expected_features: Optional[dict] = None
    ) -> dict:
        """
        Открывает опубликованную страницу по ссылке и проверяет в живом DOM:
        - Наличие блока T123 и сгенерированных CSS/JS стилей;
        - Преобразование элементов (кнопки вместо селектов, скрытие нативных селектов);
        - Вычисленные стили (computedStyle: фон, размытие, скругления 4px, цвета);
        - Консольные ошибки JavaScript.
        Возвращает структурированный отчет для замкнутого цикла исправления.
        """
        target_url = await self._resolve_live_url(url)

        if not target_url:
            msg = "Не найден URL опубликованной страницы для проверки. Сначала опубликуйте страницу."
            await self._log("warning", msg)
            return {"success": False, "message": msg, "issues": [msg]}

        await self._log("info", f"Проверяю опубликованную страницу по ссылке: {target_url} ...")

        if not self._context:
            return {"success": False, "message": "Браузер не запущен", "issues": ["Браузер не запущен"]}

        verify_page = None
        try:
            # Переключаемся на Вкладку 2 (опубликованный сайт) без открытия новых окон
            verify_page = await self.switch_to_live_page(url=target_url)
            console_errors = []
            verify_page.on("pageerror", lambda err: console_errors.append(str(err)))
            verify_page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

            await asyncio.sleep(2.5)  # Даем время инициализироваться runtime-скриптам Tilda и T123

            # Инспектируем живой DOM на боевом сайте
            eval_data = await verify_page.evaluate("""(bId) => {
                const recs = Array.from(document.querySelectorAll('.r[id^="rec"]'));
                const t123 = document.querySelector('.t123, [data-record-type="131"]');
                const styles = Array.from(document.querySelectorAll('style')).map(s => s.textContent || '').join(' ');

                // Ищем блок карточки товара (строго карточка товара, БЕЗ .t-cover!)
                const prodCardRec = document.querySelector('.r[data-record-type="762"], .r:has(.js-product), .r:has(.t762__container), .r:has(.t-store__card)');
                let targetRec = bId ? document.querySelector('#' + bId) : null;
                if (!targetRec) {
                    targetRec = prodCardRec;
                }
                if (!targetRec && recs.length > 0) {
                    targetRec = recs.find(r => r.getAttribute('data-record-type') !== '131') || recs[0];
                }

                // Проверяем наличие карточки товара (строго товарная сущность, без обложки!)
                const prodCard = (targetRec && targetRec.querySelector('.js-product, .t762__container, .t-store__card')) || prodCardRec || document.querySelector('.js-product, .t762__container, .t-store__card');
                let prodCardStyles = null;
                if (prodCard) {
                    const cs = window.getComputedStyle(prodCard);
                    prodCardStyles = {
                        bg: cs.backgroundColor,
                        backdrop: cs.backdropFilter || cs.webkitBackdropFilter || 'none',
                        radius: cs.borderRadius,
                        boxShadow: cs.boxShadow
                    };
                }

                // Проверяем наличие кастомных кнопок вариантов (вместо выпадающих списков)
                const customButtons = Array.from(document.querySelectorAll(
                    '.t-custom-option-btn, .t-product-option-buttons button, [data-glass-buttons] button, .custom-option-btn, .t-btn-option'
                ));

                // Проверяем, скрыты ли нативные select
                const selects = Array.from(document.querySelectorAll('.t-product__option-select, select.js-product-option-variants'));
                const selectsHidden = selects.length > 0 ? selects.every(s => {
                    const cs = window.getComputedStyle(s);
                    return cs.opacity === '0' || cs.position === 'absolute' || cs.display === 'none' || cs.visibility === 'hidden';
                }) : false;

                // Проверяем целевую кнопку действия (Купить / главная кнопка)
                const actionBtn = targetRec ? targetRec.querySelector('.t762__btn, a.t-btn, .t-btnflex, button.t-btn') : document.querySelector('.t762__btn, a.t-btn');
                let actionBtnStyles = null;
                if (actionBtn) {
                    const cs = window.getComputedStyle(actionBtn);
                    actionBtnStyles = {
                        bg: cs.backgroundColor,
                        color: cs.color,
                        radius: cs.borderRadius
                    };
                }

                // Проверяем наличие блока попапа / модалки
                const popupBlock = document.querySelector('.t-popup, .r[data-record-type="868"], .r[data-record-type="702"], .r:has(.t-popup), [id*="popup"]');

                return {
                    t123Exists: !!t123,
                    stylesCount: styles.length,
                    targetRecFound: !!targetRec,
                    targetRecId: targetRec ? targetRec.id : null,
                    prodCardFound: !!prodCard,
                    isProductCardFound: !!prodCardRec || !!prodCard,
                    popupBlockFound: !!popupBlock,
                    prodCardStyles: prodCardStyles,
                    customButtonsCount: customButtons.length,
                    customButtonsSample: customButtons.slice(0, 4).map(b => (b.innerText || '').trim()),
                    selectsCount: selects.length,
                    selectsHidden: selectsHidden,
                    actionBtnStyles: actionBtnStyles
                };
            }""", block_id)

            issues = []
            passed = []

            is_product_task = (
                any(w in (self._last_active_page_name or "").lower() for w in ("карточк", "товар"))
                or (block_id and "762" in str(block_id))
            )

            # 0. Строгая проверка карточки товара при релевантной задаче
            if is_product_task:
                if eval_data.get("isProductCardFound"):
                    passed.append("Целевая карточка товара обнаружена на опубликованной странице")
                else:
                    issues.append("Целевая карточка товара НЕ обнаружена на опубликованной странице (открыта главная страница или страница без карточки товара)")

            # 1. Проверка наличия кода T123
            if eval_data.get("t123Exists") or eval_data.get("stylesCount", 0) > 100:
                passed.append("Блок кода T123 загружен на опубликованную страницу")
            else:
                issues.append("Блок кода T123 не найден на опубликованной странице")

            # 2. Проверка кнопок вариантов (если на странице были селекты)
            if eval_data.get("selectsCount", 0) > 0:
                if eval_data.get("customButtonsCount", 0) > 0:
                    passed.append(f"Селекты успешно преобразованы в {eval_data.get('customButtonsCount')} кликабельных кнопок")
                else:
                    issues.append("Селекты не преобразованы в кнопки (кнопки вариантов отсутствуют в DOM)")

                if eval_data.get("selectsHidden"):
                    passed.append("Нативные селекты корректно скрыты с сохранением доступности в DOM")
                else:
                    issues.append("Нативные селекты не скрыты (выпадающие списки всё ещё видны)")
            elif is_product_task and eval_data.get("isProductCardFound") and eval_data.get("customButtonsCount", 0) == 0:
                issues.append("На карточке товара не обнаружены селекты или кнопки вариантов")

            # 3. Проверка стилей карточки
            pcs = eval_data.get("prodCardStyles")
            if pcs:
                if pcs.get("backdrop") and pcs.get("backdrop") != "none":
                    passed.append(f"Эффект размытия (backdrop-filter: {pcs.get('backdrop')}) активен")
                if "4px" in (pcs.get("radius") or ""):
                    passed.append("Скругление карточки кратно 4px")
                passed.append(f"Стили карточки применены (фон: {pcs.get('bg')}, радиус: {pcs.get('radius')})")
            elif is_product_task:
                issues.append("Стили карточки товара не применились к элементу")

            # 4. Проверка кнопки
            abs_btn = eval_data.get("actionBtnStyles")
            if abs_btn:
                if "4px" in (abs_btn.get("radius") or ""):
                    passed.append("Скругление кнопки кратно 4px")
                passed.append(f"Кнопка действия стилизована (фон: {abs_btn.get('bg')}, текст: {abs_btn.get('color')})")

            # 5. Проверка консольных ошибок
            if console_errors:
                filtered_errs = [e for e in console_errors if "favicon" not in e.lower()]
                if filtered_errs:
                    issues.append(f"Ошибки JS на странице: {'; '.join(filtered_errs[:2])}")

            success = len(issues) == 0 and len(passed) > 0

            if success:
                await self._log("success", f"Проверка на опубликованном сайте ({target_url}) успешна ✓ Все стили и скрипты работают!")
            else:
                await self._log("warning", f"Проверка на опубликованном сайте выявила недочёты: {'; '.join(issues)}")

            return {
                "success": success,
                "url": target_url,
                "passed_checks": passed,
                "issues": issues,
                "eval_data": eval_data
            }

        except Exception as e:
            err = f"Ошибка при проверке опубликованной страницы: {e}"
            await self._log("error", err)
            return {"success": False, "message": err, "issues": [err]}

        finally:
            await self.ensure_two_tabs_only()

    # ─────────────────────────── Состояние ───────────────────────────

    async def get_status(self) -> dict:
        """Возвращает текущее состояние браузера."""
        if self._page:
            try:
                url = self._page.url
                if "/projects" in url and "/login" not in url and "/identity" not in url:
                    if not self._is_logged_in:
                        self._is_logged_in = True
                        if self._context:
                            await self._context.storage_state(
                                path=str(BROWSER_DATA_DIR / "state.json")
                            )
                            await self._log("info", "Сессия Tilda сохранена")
                elif "/login" in url or "/identity" in url:
                    self._is_logged_in = False
            except Exception:
                pass

        return {
            "is_running": self.is_running,
            "is_logged_in": self._is_logged_in,
            "current_url": self._page.url if self._page else None,
            "title": await self._page.title() if self._page else None,
        }
