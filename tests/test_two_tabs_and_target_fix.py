import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock

# Мокаем google.genai на случай отсутствия локального SDK
if "google" not in sys.modules:
    sys.modules["google"] = MagicMock()
if "google.genai" not in sys.modules:
    sys.modules["google.genai"] = MagicMock()

from backend.agent import Agent
from backend.browser import BrowserController


def test_rectarget_sanitizer_in_fallback_grounding():
    agent = Agent()
    agent._last_target_block_id = "rec4671108001"

    template_code = """
    <style>
    #recTARGET .t762__container, #recTARGET .js-product {
        background: rgba(255, 255, 255, 0.72) !important;
        border-radius: 4px !important;
    }
    #recTARGET select.t-product__option-select {
        opacity: 0 !important;
    }
    </style>
    <script>
    (function() {
        var root = document.querySelector('#recTARGET');
        if (!root) return;
        console.log('Target block initialized: recTARGET');
    })();
    </script>
    """

    fake_dom = {
        "blockId": "rec4671108001",
        "recordType": "762",
        "recordCode": "ST205",
        "mainContainers": [".t762__container", ".js-product"],
        "selects": [{"name": "Цвет"}],
        "buttons": [{"text": "Купить"}]
    }

    grounded = agent._fallback_ground_code(template_code, fake_dom, "стилизуй под гласоморфизм")

    assert "#recTARGET" not in grounded, "Обнаружен плейсхолдер #recTARGET в результирующем коде!"
    assert "recTARGET" not in grounded, "Обнаружен плейсхолдер recTARGET в результирующем коде!"
    assert "#rec4671108001" in grounded, "Реальный ID блока не подставлен в селекторы!"
    assert "document.querySelector('#rec4671108001')" in grounded, "Реальный ID блока не подставлен в JS скрипт!"
    print("[OK] Тест санитайзера recTARGET в fallback_ground_code пройден!")


async def test_ground_code_with_dom_rectarget_elimination():
    agent = Agent()
    agent._last_target_block_id = "rec4671108001"

    template_code = """
    <style>
    #recTARGET .t762__container {
        backdrop-filter: blur(16px) !important;
    }
    </style>
    <script>
    var root = document.querySelector('#recTARGET');
    </script>
    """

    fake_dom = {
        "blockId": "rec4671108001",
        "recordType": "762",
        "recordCode": "ST205",
        "mainContainers": [".t762__container", ".js-product"],
        "selects": [],
        "buttons": []
    }

    # Даже если код длинный (> 300 символов), плейсхолдер обязан быть уничтожен
    long_code = template_code + "\n/* " + ("A" * 350) + " */"
    res = await agent._ground_code_with_dom(long_code, fake_dom, "минимализм")

    assert "#recTARGET" not in res, "Плейсхолдер #recTARGET пропущен в _ground_code_with_dom!"
    assert "recTARGET" not in res, "Плейсхолдер recTARGET пропущен в _ground_code_with_dom!"
    assert "#rec4671108001" in res, "Реальный ID блока не внедрен в _ground_code_with_dom!"
    print("[OK] Тест гарантированной ликвидации recTARGET в _ground_code_with_dom пройден!")


def test_browser_two_tabs_fields():
    b = BrowserController()
    assert hasattr(b, "_admin_page"), "BrowserController не имеет поля _admin_page"
    assert hasattr(b, "_live_page"), "BrowserController не имеет поля _live_page"
    assert hasattr(b, "switch_to_admin"), "BrowserController не имеет метода switch_to_admin"
    assert hasattr(b, "switch_to_live_page"), "BrowserController не имеет метода switch_to_live_page"
    assert hasattr(b, "ensure_two_tabs_only"), "BrowserController не имеет метода ensure_two_tabs_only"
    assert hasattr(b, "inspect_live_page_dom"), "BrowserController не имеет метода inspect_live_page_dom"
    print("[OK] Тест наличия методов двухвкладочной архитектуры в BrowserController пройден!")


if __name__ == "__main__":
    test_rectarget_sanitizer_in_fallback_grounding()
    asyncio.run(test_ground_code_with_dom_rectarget_elimination())
    test_browser_two_tabs_fields()
    print("Все тесты двухвкладочной архитектуры и ликвидации recTARGET успешно пройдены!")
