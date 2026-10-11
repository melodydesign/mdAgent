"""
Тесты для функционала настройки стилей блоков Tilda (edit_block_settings).
"""

import unittest
from backend.browser import normalize_block_settings_payload
from backend.agent import MUTATING_ACTIONS, Agent
from backend.memory import MemoryManager


class TestBlockSettings(unittest.TestCase):
    def test_normalize_block_settings_colors(self):
        """Проверка нормализации цветов (добавление #, удаление пробелов)."""
        raw = {
            "title_color": "ffffff",
            "btn_bg_color": "#ff0055",
            "bg_color": " 000000 ",
            "descr_color": "333",
        }
        normalized = normalize_block_settings_payload(raw)
        self.assertEqual(normalized.get("title_color"), "#ffffff")
        self.assertEqual(normalized.get("btn_bg_color"), "#ff0055")
        self.assertEqual(normalized.get("bg_color"), "#000000")
        self.assertEqual(normalized.get("descr_color"), "#333")

    def test_normalize_block_settings_sizes_and_radii(self):
        """Проверка нормализации размеров шрифтов и радиусов скругления."""
        raw = {
            "title_size": "44px",
            "descr_size": 18,
            "btn_radius": "30px",
            "btn2_radius": 0,
        }
        normalized = normalize_block_settings_payload(raw)
        self.assertEqual(normalized.get("title_size"), "44")
        self.assertEqual(normalized.get("descr_size"), "18")
        self.assertEqual(normalized.get("btn_radius"), "30")
        self.assertEqual(normalized.get("btn2_radius"), "0")

    def test_normalize_block_settings_filters_empty(self):
        """Пустые или None значения должны отсекаться."""
        raw = {
            "title_color": None,
            "btn_radius": "",
            "bg_color": "   ",
            "title_size": "36",
        }
        normalized = normalize_block_settings_payload(raw)
        self.assertNotIn("title_color", normalized)
        self.assertNotIn("btn_radius", normalized)
        self.assertNotIn("bg_color", normalized)
        self.assertEqual(normalized.get("title_size"), "36")

    def test_mutating_actions_registration(self):
        """Действие edit_block_settings должно быть зарегистрировано как мутирующее."""
        self.assertIn("edit_block_settings", MUTATING_ACTIONS)
        memory = MemoryManager()
        # Проверяем, что MemoryManager сохраняет цепочку с edit_block_settings
        sanitized = memory.sanitize_actions([
            {"action": "edit_block_settings", "params": {"btn_radius": "30"}, "description": "Скруглить кнопки"}
        ])
        # sanitize_actions гарантирует наличие скриншота в конце (итого 2 действия)
        self.assertEqual(len(sanitized), 2)
        self.assertEqual(sanitized[0]["action"], "edit_block_settings")
        self.assertEqual(sanitized[1]["action"], "screenshot")

    def test_agent_decomposition_step(self):
        """Проверка декомпозиции действия edit_block_settings в понятный шаг плана."""
        agent = Agent()
        actions = [
            {
                "action": "edit_block_settings",
                "params": {
                    "title_color": "#ffffff",
                    "title_size": "48",
                    "btn_bg_color": "#ffdd00",
                    "btn_radius": "30",
                },
                "description": ""
            }
        ]
        steps = agent._decompose_into_user_steps(actions, "Настрой стили блока")
        self.assertGreater(len(steps), 0)
        first_step = steps[0]
        self.assertIn("стил", first_step["text"].lower())
        self.assertEqual(first_step["actions"][0]["action"], "edit_block_settings")


if __name__ == "__main__":
    unittest.main()
