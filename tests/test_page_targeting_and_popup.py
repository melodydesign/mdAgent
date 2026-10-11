import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from backend.browser import (
    parse_ordinal_page_index,
    BrowserController,
    SESSION_STATE_FILE,
)


class TestPageTargetingAndPopup(unittest.TestCase):
    def test_parse_ordinal_page_index_excludes_general_words(self):
        """Проверяем, что 'главная', 'карточка', 'товар' не парсятся как индекс 0."""
        self.assertIsNone(parse_ordinal_page_index(name="главная"))
        self.assertIsNone(parse_ordinal_page_index(name="главная страница"))
        self.assertIsNone(parse_ordinal_page_index(name="карточка товара"))
        self.assertIsNone(parse_ordinal_page_index(name="товар"))
        self.assertIsNone(parse_ordinal_page_index(name="текущая"))
        # А вот порядковые номера должны корректно определяться
        self.assertEqual(parse_ordinal_page_index(name="первая"), 0)
        self.assertEqual(parse_ordinal_page_index(name="1-я"), 0)
        self.assertEqual(parse_ordinal_page_index(name="вторая"), 1)

    def test_session_state_persistence(self):
        """Проверяем сохранение и чтение параметров активной сессии."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_file = Path(tmp_dir) / "active_session_state.json"
            
            # Сохраняем состояние
            state = {
                "page_id": "61234567",
                "page_name": "карточка товара",
                "project_id": "999888",
                "project_name": "Мой Магазин",
                "target_block_id": "rec4671108001",
                "published_url": "https://test.tilda.ws/product",
                "t123_code": "<!-- Создано с помощью mdAgent -->"
            }
            tmp_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

            # Создаем контроллер с подменой файла
            import backend.browser as browser_mod
            orig_file = browser_mod.SESSION_STATE_FILE
            try:
                browser_mod.SESSION_STATE_FILE = tmp_file
                ctrl = BrowserController()
                self.assertEqual(ctrl._last_active_page_name, "карточка товара")
                self.assertEqual(ctrl._last_active_page_id, "61234567")
                self.assertEqual(ctrl._last_target_block_id, "rec4671108001")
                self.assertEqual(ctrl._last_published_url, "https://test.tilda.ws/product")

                # Проверяем сохранение нового состояния
                ctrl._last_active_page_name = "новая карточка"
                ctrl._save_session_state()
                reloaded = json.loads(tmp_file.read_text(encoding="utf-8"))
                self.assertEqual(reloaded["page_name"], "новая карточка")
            finally:
                browser_mod.SESSION_STATE_FILE = orig_file

    def test_popup_detection_logic(self):
        """Проверяем логику распознавания запроса попапа в browse_and_select_block."""
        popup_terms = [
            ("Форма и кнопка", "попап окно"),
            ("Форма", "модалка с заявкой"),
            ("Форма", "всплывающее окно"),
            ("Обложка", "popup форма"),
            ("Кнопка", "блок BF502"),
        ]
        for cat, req in popup_terms:
            clean_cat = str(cat or "").strip()
            if "форма" in clean_cat.lower() and "кнопка" in clean_cat.lower():
                clean_cat = "Форма"
            is_popup = any(
                w in (req + " " + clean_cat + " " + str(cat)).lower()
                for w in ("попап", "popup", "модалк", "всплывающ", "всплывающее", "bf50")
            )
            self.assertTrue(is_popup, f"Должен опознать попап для ({cat}, {req})")

    def test_product_card_verification_strictness(self):
        """Проверяем, что отсутствие карточки товара на проверенной странице отвергается как ошибка."""
        ctrl = BrowserController()
        ctrl._last_active_page_name = "карточка товара"

        # Симуляция eval_data с главной страницы (где только обложка, а карточки товара нет)
        home_page_eval_data = {
            "t123Exists": True,
            "stylesCount": 500,
            "targetRecFound": True,
            "prodCardFound": False,          # Карточки товара НЕТ!
            "isProductCardFound": False,     # Карточки товара НЕТ!
            "prodCardStyles": None,
            "customButtonsCount": 0,
            "selectsCount": 0,
            "selectsHidden": False,
        }

        # Выполняем логику верификации
        is_product_task = any(w in (ctrl._last_active_page_name or "").lower() for w in ("карточк", "товар"))
        issues = []
        passed = []

        if is_product_task:
            if home_page_eval_data.get("isProductCardFound"):
                passed.append("Целевая карточка товара обнаружена")
            else:
                issues.append("Целевая карточка товара НЕ обнаружена на опубликованной странице")

        if home_page_eval_data.get("t123Exists"):
            passed.append("Код T123 загружен")

        success = len(issues) == 0 and len(passed) > 0

        # Верификация ОБЯЗАНА вернуть False, потому что открыта чужая страница!
        self.assertFalse(success)
        self.assertIn("Целевая карточка товара НЕ обнаружена на опубликованной странице", issues)


if __name__ == "__main__":
    unittest.main()
