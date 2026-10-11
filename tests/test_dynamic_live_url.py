import asyncio
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Мокаем google.genai на случай отсутствия локального SDK
if "google" not in sys.modules:
    sys.modules["google"] = MagicMock()
if "google.genai" not in sys.modules:
    sys.modules["google.genai"] = MagicMock()

from backend.browser import BrowserController
from backend.gemini_client import SYSTEM_PROMPT


async def test_resolve_live_url_prefers_active_published_url():
    browser = BrowserController()
    browser._last_published_url = "https://custom-shop-domain.com/shoes"

    # Если передан пустой URL — должен вернуться активный опубликованный URL
    resolved = await browser._resolve_live_url(None)
    assert resolved == "https://custom-shop-domain.com/shoes", f"Ожидалось https://custom-shop-domain.com/shoes, получено {resolved}"

    resolved_empty = await browser._resolve_live_url("")
    assert resolved_empty == "https://custom-shop-domain.com/shoes", f"Ожидалось https://custom-shop-domain.com/shoes, получено {resolved_empty}"
    print("[OK] test_resolve_live_url_prefers_active_published_url пройден")


async def test_resolve_live_url_rejects_stale_template():
    browser = BrowserController()
    browser._last_published_url = "https://my-brand-new-site.ru/catalog"

    # Если ИИ попытался передать устаревший шаблонный URL site-md-z4khkb
    stale_url = "https://site-md-z4khkb.tilda.ws/tproducty"
    resolved = await browser._resolve_live_url(stale_url)

    # Устаревший шаблон должен быть отброшен в пользу реального URL проекта
    assert resolved == "https://my-brand-new-site.ru/catalog", f"Ожидался URL проекта, получено {resolved}"
    assert "site-md-z4khkb" not in resolved, "Устаревший шаблон не был отфильтрован!"
    print("[OK] test_resolve_live_url_rejects_stale_template пройден")


async def test_resolve_live_url_accepts_valid_custom_url():
    browser = BrowserController()
    browser._last_published_url = "https://old-site.tilda.ws/page1"

    new_custom_url = "https://client-agency.com/portfolio"
    resolved = await browser._resolve_live_url(new_custom_url)

    assert resolved == new_custom_url, f"Ожидалось {new_custom_url}, получено {resolved}"
    assert browser._last_published_url == new_custom_url, "Кэш _last_published_url не обновился"
    print("[OK] test_resolve_live_url_accepts_valid_custom_url пройден")


async def test_cache_reset_on_open_project_and_page():
    browser = BrowserController()
    browser._last_published_url = "https://some-client.tilda.ws/page"
    browser._last_target_block_id = "rec999888777"
    browser._last_inspected_dom = {"blockId": "rec999888777"}

    # Проверяем метод open_project: сбрасывает кэши
    try:
        await browser.open_project(name="Новый проект клиента")
    except Exception:
        pass

    assert browser._last_published_url is None, "Кэш _last_published_url не сбросился при open_project!"
    assert browser._last_target_block_id is None, "Кэш _last_target_block_id не сбросился при open_project!"
    assert browser._last_inspected_dom is None, "Кэш _last_inspected_dom не сбросился при open_project!"

    # Заполняем снова
    browser._last_published_url = "https://page1.tilda.ws"
    browser._last_target_block_id = "rec123"
    browser._last_inspected_dom = {"blockId": "rec123"}

    try:
        await browser.open_page(name="Контакты")
    except Exception:
        pass

    assert browser._last_published_url is None, "Кэш _last_published_url не сбросился при open_page!"
    assert browser._last_target_block_id is None, "Кэш _last_target_block_id не сбросился при open_page!"
    assert browser._last_inspected_dom is None, "Кэш _last_inspected_dom не сбросился при open_page!"
    print("[OK] test_cache_reset_on_open_project_and_page пройден")


def test_system_prompt_has_no_hardcoded_urls_and_strict_rule():
    # Проверяем, что в системном промпте нет старого хардкода
    assert "site-md-z4khkb" not in SYSTEM_PROMPT, "В системном промпте обнаружен хардкод site-md-z4khkb!"

    # Проверяем наличие строжайшего запрета на хардкод URL
    assert "КАТЕГОРИЧЕСКИЙ ЗАПРЕТ НА ХАРДКОД ССЫЛОК И АДРЕСОВ САЙТОВ" in SYSTEM_PROMPT, "Правило 23 отсутствует в промпте!"
    assert 'url=""' in SYSTEM_PROMPT or "url=''" in SYSTEM_PROMPT or '{"url": ""}' in SYSTEM_PROMPT, "Указание на url='' отсутствует!"
    print("[OK] test_system_prompt_has_no_hardcoded_urls_and_strict_rule пройден")


async def main():
    print("Запуск тестов динамического определения URL боевого сайта...")
    await test_resolve_live_url_prefers_active_published_url()
    await test_resolve_live_url_rejects_stale_template()
    await test_resolve_live_url_accepts_valid_custom_url()
    await test_cache_reset_on_open_project_and_page()
    test_system_prompt_has_no_hardcoded_urls_and_strict_rule()
    print("\n ВСЕ ТЕСТЫ ДИНАМИЧЕСКОГО URL УСПЕШНО ПРОЙДЕНЫ! ")


if __name__ == "__main__":
    asyncio.run(main())
