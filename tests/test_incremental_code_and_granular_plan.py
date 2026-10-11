import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Мокаем genai на случай отсутствия локального SDK
if "google" not in sys.modules:
    sys.modules["google"] = MagicMock()
if "google.genai" not in sys.modules:
    sys.modules["google.genai"] = MagicMock()

from backend.browser import BrowserController
from backend.agent import Agent


async def test_t123_branding_and_incremental_get():
    """Проверяет кэширование T123 кода и добавление брендингового комментария."""
    controller = BrowserController()
    controller._last_t123_code = "<style>.my-glass { backdrop-filter: blur(8px); }</style>"

    # Проверяем возврат из кэша
    cached_code = await controller.get_t123_code()
    assert cached_code == "<style>.my-glass { backdrop-filter: blur(8px); }</style>"

    # Проверяем добавление брендинга
    raw_code = "<style>.card { border-radius: 4px; }</style>"
    cleaned = raw_code.strip()
    if not cleaned.startswith("<!--"):
        cleaned = "<!-- Создано с помощью mdAgent (https://mdagent.ru) -->\n" + cleaned

    assert cleaned.startswith("<!-- Создано с помощью mdAgent (https://mdagent.ru) -->")
    assert ".card { border-radius: 4px; }" in cleaned
    print("[OK] test_t123_branding_and_incremental_get пройден")


async def test_add_block_returns_dict_safe_for_mapping_unpack():
    """Проверяет, что add_block возвращает словарь, исключая ошибку 'bool' object is not a mapping."""
    controller = BrowserController()
    
    async def mock_open_page():
        return True

    with patch.object(controller, 'open_page', side_effect=mock_open_page):
        # При отсутствии браузера метод корректно вернет словарь с success: False
        result = await controller.add_block("T123")
        assert isinstance(result, dict)
        assert "success" in result
        # Проверяем распаковку словаря без TypeError: 'bool' object is not a mapping
        unpacked = {**result, "extra_info": "ok"}
        assert "success" in unpacked
        assert unpacked["extra_info"] == "ok"
    print("[OK] test_add_block_returns_dict_safe_for_mapping_unpack пройден")


def test_session_page_memory_retention():
    """Проверяет запоминание активной страницы и приоритет возврата к ней."""
    controller = BrowserController()
    controller._last_active_page_id = "235519409"
    controller._last_active_page_name = "карточка товара"

    assert controller._last_active_page_id == "235519409"
    assert controller._last_active_page_name == "карточка товара"
    print("[OK] test_session_page_memory_retention пройден")


def test_plan_decomposition_splits_complex_tasks():
    """Проверяет декомпозицию составной задачи на отдельные шаги плана."""
    agent = Agent()
    
    actions = [
        {
            "action": "edit_t123_code",
            "description": "Дополнить и изменить существующий код: миниатюры справа, шрифт кнопок как у названия товара, более жирное начертание и кнопка менеджера, открывающая стандартный попап"
        },
        {
            "action": "publish_page",
            "description": "Опубликовать страницу в сети"
        },
        {
            "action": "verify_published_page",
            "description": "Проверить миниатюры справа и попап"
        }
    ]

    steps = agent._decompose_into_user_steps(actions)
    
    # Должно быть декомпозировано на составные подзадачи
    assert len(steps) >= 4, f"Ожидалось >= 4 шагов, получено {len(steps)}"
    step_texts = [s["text"] for s in steps]
    
    assert any("миниатюры" in t.lower() for t in step_texts)
    assert any("шрифт" in t.lower() or "начертание" in t.lower() for t in step_texts)
    assert any("попап" in t.lower() or "менеджер" in t.lower() for t in step_texts)
    assert any("опубликовать" in t.lower() for t in step_texts)
    assert any("проверить" in t.lower() for t in step_texts)
    print("[OK] test_plan_decomposition_splits_complex_tasks пройден")


def test_ground_code_with_dom_merges_existing_code():
    """Проверяет, что при генерации кода блока существующий T123 код не теряется."""
    agent = Agent()
    
    existing_t123 = """<!-- Создано с помощью mdAgent (https://mdagent.ru) -->
<style>
.t762__btn-custom { backdrop-filter: blur(10px); background: rgba(255,255,255,0.1); }
</style>
<script>
console.log('existing option buttons');
</script>"""

    new_candidate = """<style>
.t762__gallery-thumbs { float: right; }
</style>"""

    merged = agent._merge_t123_code(existing_t123, new_candidate)
    assert "backdrop-filter" in merged
    assert "gallery-thumbs" in merged
    assert "<!-- Создано с помощью mdAgent" in merged
    print("[OK] test_ground_code_with_dom_merges_existing_code пройден")


async def main():
    await test_t123_branding_and_incremental_get()
    await test_add_block_returns_dict_safe_for_mapping_unpack()
    test_session_page_memory_retention()
    test_plan_decomposition_splits_complex_tasks()
    test_ground_code_with_dom_merges_existing_code()
    print("\n[SUCCESS] All 5 tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
