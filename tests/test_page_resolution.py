import unittest
from backend.browser import parse_ordinal_page_index, is_page_not_found_content


class TestPageResolution(unittest.TestCase):
    def test_parse_ordinal_page_index_from_page_id(self):
        # Короткие ID (1, 2, 3...) — это порядковые номера страниц
        self.assertEqual(parse_ordinal_page_index(page_id="1"), 0)
        self.assertEqual(parse_ordinal_page_index(page_id=1), 0)
        self.assertEqual(parse_ordinal_page_index(page_id="2"), 1)
        self.assertEqual(parse_ordinal_page_index(page_id=2), 1)
        self.assertEqual(parse_ordinal_page_index(page_id="3"), 2)
        self.assertEqual(parse_ordinal_page_index(page_id="4"), 3)

        # Реальные Tilda ID (> 9999) — это не порядковые номера
        self.assertIsNone(parse_ordinal_page_index(page_id="61234567"))
        self.assertIsNone(parse_ordinal_page_index(page_id=987654321))

    def test_parse_ordinal_page_index_from_name(self):
        # Названия с указанием порядкового номера
        self.assertEqual(parse_ordinal_page_index(name="первая"), 0)
        self.assertEqual(parse_ordinal_page_index(name="первая страница"), 0)
        self.assertEqual(parse_ordinal_page_index(name="вторая"), 1)
        self.assertEqual(parse_ordinal_page_index(name="вторая страница"), 1)
        self.assertEqual(parse_ordinal_page_index(name="второй страницы"), 1)
        self.assertEqual(parse_ordinal_page_index(name="2-я страница"), 1)
        self.assertEqual(parse_ordinal_page_index(name="третья страница"), 2)
        self.assertEqual(parse_ordinal_page_index(name="четвертая страница"), 3)

        # Обычные текстовые названия страниц не являются порядковыми
        self.assertIsNone(parse_ordinal_page_index(name="О компании"))
        self.assertIsNone(parse_ordinal_page_index(name="mdAgent - AI лендинг"))
        self.assertIsNone(parse_ordinal_page_index(name="Тарифы и цены"))

    def test_is_page_not_found_content(self):
        # Детекция 404 страницы Tilda
        tilda_404_html = """
        <html>
            <body>
                <div class="td-page-not-found">
                    <h1>Страница не существует</h1>
                    <a href="/projects/">К списку проектов</a>
                </div>
            </body>
        </html>
        """
        self.assertTrue(is_page_not_found_content(tilda_404_html))
        self.assertTrue(is_page_not_found_content("Ошибка: Страница не существует"))
        self.assertTrue(is_page_not_found_content("Page not found. К списку проектов"))

        # Обычный редактор Tilda не должен определяться как 404
        tilda_editor_html = """
        <html>
            <body>
                <div id="page-actions">
                    <a href="/page/settings/?pageid=1234567">Настройки</a>
                </div>
                <div class="tp-record-edit">Блок 1</div>
            </body>
        </html>
        """
        self.assertFalse(is_page_not_found_content(tilda_editor_html))


if __name__ == "__main__":
    unittest.main()
