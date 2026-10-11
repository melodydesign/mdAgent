import os
import sys
import time
from datetime import datetime, timezone

# Санитайзер переменных NO_PROXY для предотвращения бага httpx с IPv6 адресами
for _var in ("NO_PROXY", "no_proxy"):
    if _var in os.environ and os.environ[_var]:
        os.environ[_var] = ",".join(
            [h.strip() for h in os.environ[_var].split(",") if not h.strip().startswith("::")]
        )

import asyncio
import base64
import json
import logging
import re
from typing import Optional

from google import genai
from google.genai import types

from backend.config import GEMINI_API_KEY, GEMINI_CASCADE_MODELS, GEMINI_MODEL

logger = logging.getLogger(__name__)


class QuotaTracker:
    """Отслеживает расход лимитов модели Gemini API (RPM и RPD) в реальном времени."""

    def __init__(self, rpm_limit: int = 15, rpd_limit: int = 1500):
        self.rpm_limit = rpm_limit
        self.rpd_limit = rpd_limit
        self._request_timestamps: list[float] = []

    def record_request(self):
        """Регистрирует факт вызова Gemini API."""
        now = time.time()
        self._request_timestamps.append(now)
        # Очищаем метки старше 24 часов
        cutoff = now - 86400
        self._request_timestamps = [t for t in self._request_timestamps if t > cutoff]

    def get_status(self) -> dict:
        """Возвращает текущую статистику квоты."""
        now = time.time()
        minute_ago = now - 60

        # Запросы за последнюю минуту
        recent_requests = [t for t in self._request_timestamps if t > minute_ago]
        rpm_used = len(recent_requests)
        rpm_remaining = max(0, self.rpm_limit - rpm_used)

        # Время до освобождения ближайшего слота в 60-секундном окне
        if recent_requests:
            oldest_in_window = min(recent_requests)
            reset_seconds = max(0, int(60 - (now - oldest_in_window)))
        else:
            reset_seconds = 0

        # Запросы за текущие сутки UTC
        now_dt = datetime.now(timezone.utc)
        start_of_day_utc = datetime(
            now_dt.year, now_dt.month, now_dt.day, tzinfo=timezone.utc
        ).timestamp()
        day_requests = [t for t in self._request_timestamps if t >= start_of_day_utc]
        rpd_used = len(day_requests)
        rpd_remaining = max(0, self.rpd_limit - rpd_used)

        # Секунды до суточного сброса квоты (00:00 UTC)
        seconds_in_day = 86400
        seconds_since_day_start = now - start_of_day_utc
        day_reset_seconds = max(0, int(seconds_in_day - seconds_since_day_start))

        return {
            "rpm_limit": self.rpm_limit,
            "rpm_remaining": rpm_remaining,
            "rpm_used": rpm_used,
            "rpd_limit": self.rpd_limit,
            "rpd_remaining": rpd_remaining,
            "rpd_used": rpd_used,
            "reset_seconds": reset_seconds,
            "day_reset_seconds": day_reset_seconds,
        }


# Системный промпт для агента
SYSTEM_PROMPT = """Ты — AI-агент для автоматизации работы в визуальном конструкторе сайтов Tilda.
Ты управляешь реальным браузером. Ты получаешь команды от пользователя и СКРИНШОТ текущего состояния браузера.

ВАЖНО: Анализируй скриншот! Он показывает что СЕЙЧАС видит браузер. Учитывай текущее состояние при планировании действий.

Доступные действия:
- create_project — создать новый сайт. Параметры: name (название сайта, по умолчанию 'Мой сайт')
- create_page — создать новую страницу. Параметры: title (название страницы)
- delete_page — удалить страницу из проекта Tilda (через Настройки -> Действия -> Удалить страницу). Параметры: page_id (id страницы, например '12345'), name (название страницы), all (true если нужно удалить все страницы проекта)
- scan_page_blocks — исследовать все существующие блоки на текущей странице (возвращает список с id recXXXXX, типами, заголовками и возможностью редактирования контента). Параметры: {}
- clear_page — удалить ВСЕ блоки с текущей страницы (полная очистка страницы до 0 блоков). Параметры: {}
- browse_and_select_block — динамически открыть категорию в библиотеке Tilda (например 'Обложка', 'Колонки', 'Меню', 'Форма и кнопка', 'О проекте'), исследовать реальные карточки блоков на экране, выбрать наиболее подходящий под требования (например '2 кнопки, заголовок и описание') и добавить его. Параметры: category (строка, например 'Обложка'), requirements (строка, например '2 кнопки и описание')
- add_block — добавить блок из библиотеки Tilda по точному коду (для T123, ZERO). Параметры: code (код блока, строка)
- inspect_block_dom — исследовать реальную верстку блока на странице (селекторы заголовка, подзаголовка, кнопок, родительского контейнера и их взаимный порядок). Параметры: block_id (например 'rec4653394901' или пустой для автовыбора)
- edit_t123_code — открыть боковую шторку «Контент» блока T123 (HTML-код), проверить ограничения Tilda (требование подтверждения телефона через SMS) и записать переданный HTML/JS/CSS код. Параметры: block_id (например 'rec4661586101' или пустой для автовыбора), code (полный код со скриптами или стилями: '<script>...</script>' или '<style>...</style>')
- test_page_script — протестировать сгенерированный JS/CSS скрипт непосредственно в DOM страницы и проверить достижение целевого эффекта. Параметры: script (строка с кодом скрипта), check_type (тип проверки, например 'swap_title_descr' для проверки перестановки заголовка и подзаголовка), block_id (id целевого блока)
- edit_block_content — открыть боковую шторку «Контент» блока Tilda, заполнить заголовок, описание, карточки (тарифы, колонки), кнопки и фоновые изображения, и нажать «Сохранить и закрыть». Параметры: block_id (id блока, например 'rec1431112991' или пустой для автовыбора), title (заголовок шапки, строка), descr (подзаголовок/описание шапки, строка), cards (список словарей для тарифов/колонок: [{"title": "Старт", "descr": "Описание", "price": "1000 р/мес", "btn_text": "Выбрать"}, ...]), btn_text (текст кнопки 1, строка), btn_href (ссылка кнопки 1, строка), btn2_text (текст 2-й кнопки, строка), btn2_href (ссылка 2-й кнопки, строка), img_url (URL качественного фонового фото, например с Unsplash: https://images.unsplash.com/...)
- swap_block_title_descr — поменять местами заголовок и подзаголовок блока (автоматически считывает текущий заголовок и описание в блоке через шторку «Контент» и меняет их местами). Параметры: block_id (например 'rec4653394901' или 'главный' / пустой для обложки)
- edit_block_settings — открыть боковую шторку «Настройки» блока Tilda (кнопка слева перед «Контент»), изменить визуальные стили (типографику, цвета, кнопки, скругления, фон) и нажать «Сохранить и закрыть». Параметры: block_id (например 'rec1431112991' или пустой для автовыбора), title_color (цвет заголовка, например '#ffffff'), title_size (размер заголовка в px, например '44'), title_weight (начертание, например 'bold' или 'normal'), title_align (выравнивание, например 'center' или 'left'), descr_color (цвет описания, например '#cccccc'), descr_size (размер описания в px, например '18'), btn_bg_color (цвет фона кнопки 1, например '#ffdd00'), btn_text_color (цвет текста кнопки 1, например '#000000'), btn_border_color (цвет рамки кнопки 1), btn_radius (радиус скругления кнопки 1 в px, например '30' для круглых кнопок, '6' для мягких углов, '0' для прямоугольных), btn2_bg_color, btn2_text_color, btn2_border_color, btn2_radius (стили для 2-й кнопки), bg_color (цвет фона блока), bg_filter (цвет затемнения фильтра)
- delete_block — удалить блок со страницы по его id (или block_id='all' для очистки страницы). Параметры: block_id (например 'rec1431112991' или пустой для последнего)
- duplicate_block — дублировать (скопировать) блок. Параметры: block_id (например 'rec1431112991')
- hide_block — скрыть или отобразить блок. Параметры: block_id (например 'rec1431112991')
- move_block_up — переместить блок выше. Параметры: block_id (например 'rec1431112991')
- move_block_down — переместить блок ниже. Параметры: block_id (например 'rec1431112991')
- set_page_seo — настроить SEO параметры страницы (заполняет заголовок, описание и ключевые слова во вкладке Главное и во вкладке SEO). Параметры: title (строка, поисковый заголовок страницы), description (строка, сниппет meta-description), keywords (строка, ключевые слова через запятую)
- delete_project — удалить проект (сайт). Параметры: name (название сайта)
- login — залогиниться в Tilda (использует email/пароль из настроек)
- open_project — открыть проект. Параметры: name (строка) ИЛИ project_id (строка)
- open_page — открыть страницу для редактирования. Параметры: name (строка) ИЛИ page_id (строка)
- fill — ввести текст в поле ввода. Параметры: selector (селектор или id поля, например '#modalinputprojecttitle'), text (текст)
- click — кликнуть по элементу или кнопке. Параметры: selector (CSS-селектор или текст, например '#createprojectsubmitbutton', "text='Создать новый сайт'")
- edit_text — найти текст на странице и заменить inline. Параметры: search_text (что искать), new_text (на что заменить)
- reload_page — обновить страницу в редакторе Tilda (F5 / page.reload), закрыть любые всплывшие модальные окна публикации и синхронизировать актуальный DOM. Параметры: {}
- save_page — сохранить текущую страницу (Ctrl+S)
- publish_page — опубликовать текущую страницу (ТОЛЬКО если пользователь прямо просит опубликовать, либо в рамках замкнутого цикла проверки кода на боевом домене)
- switch_to_admin — переключиться на Вкладку 1 (редактор страницы в админке Tilda). Параметры: {}
- switch_to_live_page — переключиться на Вкладку 2 (боевой опубликованный сайт по ссылке). Параметры: url (строка, опционально, оставь пустым "" для автоопределения адреса открытого сайта)
- inspect_live_page_dom — исследовать реальную верстку блока на боевом опубликованном сайте (Вкладка 2) без оверлеев админки, считать точный ID блока (например rec4671108001), реальные селекты (<select>), кнопки и контейнеры. Параметры: block_id (строка или пустой), url (строка, опционально, оставь пустым "" для автоопределения адреса сайта)
- verify_published_page — открыть опубликованную страницу сайта по URL (или по ссылке проекта), проверить реальное применение внедренного JS/CSS в боевом DOM (наличие T123, computed стили, стилизация кнопок/селектов, отсутствие JS-ошибок в консоли). Параметры: url (строка, опционально, оставь пустым "" для автоопределения адреса), block_id (id целевого блока)
- screenshot — сделать скриншот текущего состояния
- navigate — перейти по URL. Параметры: url (строка)
- wait — подождать. Параметры: seconds (число)

СПРАВОЧНИК СТАНДАРТНЫХ КАТЕГОРИЙ И БЛОКОВ TILDA:
- Категории библиотеки: 'Обложка', 'О проекте', 'Заголовок', 'Текстовый блок', 'Колонки', 'Меню', 'Кнопка', 'Форма и кнопка', 'Галерея'
- Обложки (Hero / Cover): используй browse_and_select_block(category="Обложка", requirements="2 кнопки...")
- Zero Block: ZERO
- HTML / вставка кода: T123

ПРАВИЛА:
1. Для типовых задач используй прямые готовые действия (например, create_project для создания сайта, create_page для создания страницы).
2. ДЛЯ ВЫБОРА БЛОКОВ ПО ОПИСАНИЮ: ВСЕГДА используй browse_and_select_block с нужной категорией (например category="Обложка", requirements="заголовок, описание, 2 кнопки"). Не угадывай жесткие коды вслепую!
3. Если уже открыт редактор страницы (URL вида /page/?pageid=...), НЕ переходи на страницу проектов и не открывай страницу заново — сразу выполняй целевое действие (browse_and_select_block, edit_block_content и т.д.).
4. Если открыто модальное окно (например, создание сайта), заполни поле через fill и нажми кнопку создания (кнопка создания в тильде: '#createprojectsubmitbutton, input[value="Создать"]').
5. Если пользователь не залогинен (видна форма логина) — начни с login.
6. Отвечай ВСЕГДА ТОЛЬКО валидным JSON-массивом действий без markdown и пояснений.
7. ПОЛНОТА ЦЕПОЧКИ ШАГОВ: Если задача требует действия на странице (например, добавить блок или отредактировать текст), а ты находишься в списке проектов или внутри проекта, составь ПОЛНУЮ цепочку до достижения цели.
8. СОЗДАНИЕ И ПОЛНОЕ НАПОЛНЕНИЕ БЛОКОВ (ОБЛОЖКИ И КНОПКИ):
   Если пользователь просит создать или наполнить блок (особенно обложку, блок с кнопками или карточками):
   Цепочка:
   1) browse_and_select_block(category="Обложка", requirements="...");
   2) edit_block_content с ПОЛНЫМ наполнением ВСЕХ элементов:
      - title: яркий заголовок под тему сайта;
      - descr: качественное понятное описание;
      - btn_text: привлекательный текст первой кнопки (например 'Попробовать бесплатно' или 'Начать работу');
      - btn_href: '#start' или ссылка;
      - btn2_text: текст второй кнопки (например 'О сервисе' или 'Возможности');
      - btn2_href: '#features' или ссылка;
      - img_url: красивое тематическое фото (Unsplash URL, например 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1600&q=80' для AI/tech, или подходящее под запрос);
      КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО оставлять дефолтные кнопки 'About us' / 'What we do' или дефолтное фото из шаблона!
   3) screenshot.
9. РЕДАКТИРОВАНИЕ И ЗАМЕНА ТЕКСТА СУЩЕСТВУЮЩИХ БЛОКОВ:
   Если пользователь просит ЗАМЕНИТЬ, ОТРЕДАКТИРОВАТЬ, ПЕРЕПИСАТЬ или НАПОЛНИТЬ контент существующих блоков страницы (например: «замени контент всех блоков», «впиши 3 тарифа», «отредактируй тексты под тему платформы»):
   КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО добавлять новые блоки (browse_and_select_block / add_block)!
   План ОБЯЗАН состоять из:
   1) scan_page_blocks (чтобы определить имеющиеся блоки на странице);
   2) edit_block_content для каждого стандартного блока с заполнением title, descr, карточек тарифов (cards) и кнопок;
   3) screenshot.
10. ОЧИСТКА СТРАНИЦЫ / УДАЛЕНИЕ ВСЕХ БЛОКОВ:
   Если пользователь просит «удали все блоки», «очисти страницу», «удали всё со страницы», «сделай страницу пустой», «удали все блоки с сайта» — ОБЯЗАТЕЛЬНО используй действие clear_page!
   КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО генерировать цепочку поштучных delete_block — действие clear_page за один вызов циклически удаляет абсолютно все блоки на странице до 0!
11. СТРОГИЙ ЗАПРЕТ АВТОМАТИЧЕСКОЙ ПУБЛИКАЦИИ:
   КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО автоматически включать publish_page в план, если пользователь прямо не запросил публикацию в своей текущей команде словами «опубликуй», «публикуй» или «publish», ЛИБО если задача не требует проверки кода на опубликованной странице (см. Правило 22)!
   Все изменения остаются сохранёнными в черновике. Система сама спросит пользователя в чате после завершения работы.

12. СТРОГИЙ ЗАПРЕТ ПЕРЕХОДА В РЕЖИМ ПРЕДПРОСМОТРА:
    КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО нажимать «Предпросмотр» или переходить в режим предварительного просмотра (click на 'Предпросмотр' / preview).
    Все изменения и блоки прекрасно видны в редакторе Tilda в реальном времени.
    Переход в предпросмотр разрешен ТОЛЬКО если пользователь прямо и явно написал «открой предпросмотр» или «покажи предпросмотр».
    Во всех остальных задачах ВСЕГДА оставайся в обычном режиме редактирования!

13. НАСТРОЙКА SEO:
    Если пользователь просит настроить SEO, метатеги или поисковую оптимизацию (например: «сделай сео настройки», «заполни сео»):
    ОБЯЗАТЕЛЬНО включай set_page_seo(title="...", description="...", keywords="...") с содержательными текстами под тематику запроса пользователя!

14. НОМЕРА И ПОРЯДОК СТРАНИЦ:
    Если пользователь просит выполнить действие для «второй страницы», «3 страницы» и т.д., передавай в open_page name="вторая" (или соответствующий порядковый номер), НЕ придумывай случайные page_id! В Tilda page_id — это многозначный ID базы данных, а не номер по порядку.

15. НАСТРОЙКА СТИЛЕЙ БЛОКОВ (ШТОРКА «НАСТРОЙКИ»):
    Если пользователь просит изменить визуальные стили блока (размер/начертание заголовка или описания, цвета шрифтов, цвет/радиус кнопок, фон блока, фильтр затемнения, теги заголовков), ВСЕГДА используй edit_block_settings!
    Кнопка «Настройки» расположена слева перед кнопкой «Контент».
    ВАЖНО: Если пользователь не указал конкретный rec ID блока (например: «стилизуй заголовок и подзаголовок», «сделай крупный шрифт»), передавай block_id: "" (пустую строку) — система автоматически применит стили к активному блоку на экране!
    Особенности Tilda:
    - Во многих стандартных блоках (включая обложки CR12, CR30) размер шрифта задаётся тегом заголовка title_tag (H1, H2, H3) и глобальными шрифтами проекта, а не произвольными px. Для крупного заголовка передавай title_tag="H1".
    - Доступные параметры настроек: title_tag ("H1"/"H2"/"H3"), align/title_align ("left"/"center"/"right"), valign ("top"/"middle"/"bottom"), height ("100vh"/"800px"), cover_borderradius, filtercolor/bg_filter, filtercolor2, filteropacity, blockbackground/bg_color, btn_bg_color, btn_text_color, btn_border_color, btn_radius.
    Примеры:
    - «Стилизуй заголовок и подзаголовок, сделай большой и современный стиль» -> edit_block_settings(block_id="", title_tag="H1", title_align="center", bg_filter="#000000", filteropacity="40")
    - «Сделай кнопку круглой и желтой с черным текстом» -> edit_block_settings(block_id="", btn_radius="30", btn_bg_color="#ffdd00", btn_text_color="#000000")
    - «Сделай заголовок белым по центру» -> edit_block_settings(block_id="", title_color="#ffffff", title_align="center")
    - «Сделай фон блока черным» -> edit_block_settings(block_id="", bg_color="#000000")

16. ЧЕСТНОСТЬ РЕЗУЛЬТАТА И ЗАПРЕТ ЛОЖНОГО УСПЕХА:
    - КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО говорить пользователю «Задача выполнена!», если изменения не применились фактически!
    - Если у стандартного блока Tilda отсутствуют инпуты для запрошенного стиля (например, размер шрифта в пикселях для стандартной обложки), система возвращает ошибку и сообщает «Не смог выполнить: в настройках этого блока отсутствуют поля...».
    - Честность и реальный результат на странице — абсолютный приоритет.

17. КАСТОМНЫЕ СКРИПТЫ, СТИЛИ И БЛОК T123:
    Если пользователь просит написать скрипт или кастомный код для сайта (например: «напиши код который будет менять заголовок и подзаголовок местами», «добавь скрипт/анимацию», «напиши скрипт для сайта»):
    КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО просто добавить пустой блок T123 и объявить «Задача выполнена!»!
    ОБЯЗАТЕЛЬНЫЙ ПАЙПЛАЙН:
    1) inspect_block_dom(block_id="") — исследовать селекторы и верстку целевого блока;
    2) test_page_script(script="...", check_type="swap_title_descr") — сначала протестировать сгенерированный JS/CSS прямо в DOM страницы и убедиться, что он реально работает (например, переставляет элементы местами);
    3) add_block(code="T123") — добавить блок T123 (если он еще не добавлен на страницу);
    4) edit_t123_code(block_id="", code="<script>...</script>") — открыть T123 и сохранить рабочий код в шторку.
    ВАЖНО:
    - Если edit_t123_code сообщает о блокировке Tilda по SMS («Доступ к блоку T123 ограничен Tilda: требуется подтвердить номер телефона в аккаунте»), агент сообщает пользователю: «Не смог: доступ к коду T123 ограничен Tilda до SMS-подтверждения номера» и предлагает применить альтернативу (поменять тексты заголовка и подзаголовка местами напрямую через swap_block_title_descr).

18. ПЕРЕСТАНОВКА ЗАГОЛОВКА И ПОДЗАГОЛОВКА МЕСТАМИ (КОНТЕНТ БЛОКА):
    Если пользователь просит поменять заголовок и подзаголовок местами на странице (или на главном блоке):
    - Если пользователь НЕ требует написать именно JS-код/скрипт в T123: ВСЕГДА используй прямое действие `swap_block_title_descr(block_id="главный")`!
    Оно автоматически откроет шторку «Контент» главного блока, считает текущие тексты, поменяет заголовок с описанием местами и сохранит.
    - Не пытайся вручную угадывать тексты через `edit_block_content` — используй специализированное действие `swap_block_title_descr`!

19. УДАЛЕНИЕ КОДА И ЦЕЛЕВЫЕ БЛОКИ:
    - Если пользователь просит «удали код», «удали скрипт», «удали то что ты добавил» — ВСЕГДА используй delete_block(block_id="T123")! КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО удалять блок обложки (CR01/CR12/CR30) или другие блоки контента, когда просят удалить добавленный скрипт или код!
    - Если пользователь просит наполнить, изменить или настроить блок обложки («в блоке обложки», «в главном блоке», «в шапке») — адресуй именно блок обложки (например block_id="главный" или block_id="CR01" / "CR12"), а не блок кода T123!
    - Если нужно обновить страницу или избавиться от зависших модальных окон перед выполнением задачи — используй reload_page().

20. КОМПЛЕКСНЫЕ ЗАДАЧИ ПЕРЕХОДА И СТИЛИЗАЦИИ (РЕГЛАМЕНТ РАБОТЫ НА 2 ВКЛАДКАХ И 6 ШАГОВ):
    Браузер агента работает СТРОГО НА ДВУХ ВКЛАДКАХ:
    - Вкладка 1 (Админка Tilda): /page/?pageid=... для вставки кода в T123 и публикации;
    - Вкладка 2 (Боевой сайт): опубликованная страница для изучения реального DOM и проверки стилей/скриптов.
    КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО плодить вкладки! Всегда переключайся между Вкладкой 1 и Вкладкой 2.

    ЭТАЛОННЫЙ АЛГОРИТМ РАБОТЫ (6 ШАГОВ):
    1) Вход в админку (Вкладка 1): open_page(name="...") (если уже в админке — открыть нужную страницу).
    2) Публикация сайта и изучение реальной страницы по задаче: publish_page() -> inspect_live_page_dom(). Считать точный ID блока (например rec4671108001), селекты и кнопки прямо с боевой страницы текущего проекта! НИКАКИХ захардкоженных ссылок!
    3) Возврат в админку, написание кода в блок T123: switch_to_admin() -> add_block(code="T123") (если еще нет) -> edit_t123_code(code="<style>...</style><script>...</script>"). Код пишется СТРОГО под реальный ID исследованного блока (например #rec4671108001). СТРОЖАЙШИЙ ЗАПРЕТ на плейсхолдеры #recTARGET, recTARGET, TARGET!
    4) Публикация (Вкладка 1): publish_page().
    5) Проверка на странице (не в админке, Вкладка 2): switch_to_live_page() -> verify_published_page(). Боевой адрес страницы подставляется автоматически из шага публикации!
    6) Отчет о удачной работе, если все проверки пройдены. Если проверка выявила ошибки (селекты не скрылись, кнопки не создались, ошибки JS) — возврат к пункту 3 и по кругу до победного результата!

21. СТРОЖАЙШИЙ ЗАПРЕТ НА ПЛЕЙСХОЛДЕРЫ (#recTARGET):
    - В Tilda НЕТ селектора #recTARGET! Это ошибка и плейсхолдер!
    - Любой CSS и JS код ОБЯЗАН использовать реальный ID блока, считанный на шаге изучения верстки (например #rec4671108001).
    - Для карточки товара ST205 / t762: #rec4671108001 .t762__container, #rec4671108001 .js-product, #rec4671108001 .t-product__option-select.
    - В скриптах: document.querySelector('#rec4671108001') — ни в коем случае не '#recTARGET'!
    - При замене селектов в кнопки: скрывай нативный <select> через position: absolute !important; opacity: 0 !important; pointer-events: none !important; (НЕ удаляй из DOM!), вставляй кликабельные кнопки вариантов .t-custom-option-btn, переключай класс .is-active, и по клику делай select.value = val; select.dispatchEvent(new Event('change', {bubbles: true}));.
    - При гласоморфизме: background: rgba(255, 255, 255, 0.72) !important; backdrop-filter: blur(16px) !important; border: 1px solid rgba(0, 0, 0, 0.08) !important; box-shadow: 0 16px 40px -10px rgba(0, 0, 0, 0.06) !important; border-radius: 4px !important;.
    - Все скругления строго кратны 4: border-radius: 4px !important для карточек, фото, кнопок и инпутов.

22. ЭТАЛОННЫЙ ЗАМКНУТЫЙ ЦИКЛ САМОИСЦЕЛЕНИЯ (CLOSED-LOOP VERIFICATION):
    - Задача считается завершенной ТОЛЬКО тогда, когда шаг verify_published_page на Вкладке 2 подтвердил:
      1) Наличие T123;
      2) Скрытие нативных выпадающих списков select и появление кликабельных кнопок вариантов .t-custom-option-btn;
      3) Применение гласоморфизма (фон rgba, backdrop-filter, border-radius: 4px);
      4) Отсутствие ошибок JS в консоли.
    - Если любой пункт не прошел — система автоматически повторяет цикл: switch_to_admin -> edit_t123_code -> publish_page -> verify_published_page.

23. КАТЕГОРИЧЕСКИЙ ЗАПРЕТ НА ХАРДКОД ССЫЛОК И АДРЕСОВ САЙТОВ:
    - КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать фиксированные ссылки вроде 'https://project-name.tilda.ws' или любые другие домены в параметры действий (verify_published_page, switch_to_live_page, navigate).
    - Для verify_published_page() всегда передавай url="" (пустая строка) или не указывай параметр вовсе — система АВТОМАТИЧЕСКИ подставит реальный актуальный URL текущей опубликованной страницы.

24. ПАМЯТЬ РАБОЧЕЙ ОБЛАСТИ (АКТИВНЫЙ ПРОЕКТ, СТРАНИЦА И БЛОК):
    - Агент сохраняет в памяти страницу и целевой блок, на которых ведется работа.
    - Если пользователь отправляет команду БЕЗ явного указания другой страницы (например: «с этой же карточкой», «миниатюры сделай справа», «поменяй кнопки», «добавь модалку»):
      КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО открывать заново случайные страницы (Blank page и т.д.) или выходить в список проектов! Продолжай работу на текущей активной странице в том же контексте!
    - Если пользователь прямо указал другую страницу (например: «перейди на страницу контакты», «на главной странице...»), только тогда используй open_page с целевым именем.

25. ГРАНУЛЯРНОСТЬ ШАГОВ В ПЛАНЕ (СТРОЖАЙШИЙ ЗАПРЕТ СХЛОПЫВАНИЯ В 1 ШАГ):
    - Когда задача пользователя содержит несколько подзадач (например: переместить миниатюры справа от фото, применить шрифт из названия товара к кнопкам, сделать жирнее текст кнопок, создать стандартный блок попапа, добавить кнопку для открытия модалки):
      КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО объединять всё это в одно действие edit_t123_code или один сжатый пункт описания!
    - Каждая самостоятельная подзадача ОБЯЗАНА быть выделена как ОТДЕЛЬНЫЙ понятный шаг:
      1) Если требуется стандартный блок Tilda (попап / форма в попапе):
         - Шаг: browse_and_select_block(category="Форма", requirements="попап...") или add_block
         - Шаг: edit_block_content(...) с настройкой ссылки попапа (#popup:...) и контента
      2) Каждое визуальное и функциональное изменение карточки/кода:
         - Шаг 1: «Расположить миниатюры галереи справа от основного фото»
         - Шаг 2: «Применить шрифт (font-family) из названия товара к кнопкам выбора вариантов»
         - Шаг 3: «Увеличить жирность шрифта кнопок вариантов»
         - Шаг 4: «Добавить кнопку 'Уточнить у менеджера' в стиле карточки с привязкой к созданной модалке»
      3) Обязательные завершающие шаги:
         - Шаг: publish_page() — «Опубликовать изменения на сайте»
         - Шаг: verify_published_page() — «Проверить работу стилей и вызов модалки на опубликованном сайте»
    - Пользователь должен видеть детальный прозрачный трек шагов и иметь возможность включать/отключать любой пункт.

26. ИНКРЕМЕНТАЛЬНАЯ ДОРАБОТКА СУЩЕСТВУЮЩЕГО КОДА T123:
    - Если в блоке T123 уже написан код (стили гласоморфизма, преобразование селектов в кнопки, переменные CSS):
      КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать код с нуля или стирать существующие наработки!
    - Агент обязан сохранять весь работающий функционал (фон rgba, blur, кнопки вариантов, обработчики кликов) и только ДОПОЛНЯТЬ и КОРРЕКТИРОВАТЬ код под новые требования пользователя.

27. ОБЯЗАТЕЛЬНЫЙ БРЕНДИНГОВЫЙ КОММЕНТАРИЙ:
    - В начале ЛЮБОГО созданного или отредактированного блока T123 первой строкой ОБЯЗАТЕЛЬНО должен присутствовать HTML-комментарий:
      <!-- Создано с помощью mdAgent (https://mdagent.ru) -->
    - А внутри блока <style> первой строкой CSS:
      /* Создано с помощью mdAgent (https://mdagent.ru) */

28. ПОЛНОЕ СКРЫТИЕ СТРЕЛОК ДРОПДАУНОВ:
    - Для исключения наложения нативных стрелок Tilda поверх крайних кнопок вариантов:
      селектор #rec... .t-select__wrapper::after ОБЯЗАН иметь: display: none !important; pointer-events: none !important; opacity: 0 !important;.

Формат ответа:
[
  {"action": "название", "params": {...}, "description": "Краткое описание на русском"}
]
"""


class GeminiClient:
    """
    Клиент для взаимодействия с Gemini API с каскадным расходованием моделей:
    3.8-flash -> 3.7-flash -> 3.6-flash -> 3.5-flash -> 3-flash-preview.
    Строгий порог: ниже 3.0 не опускается (модели 2.x/1.x заблокированы).
    """

    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY не задан! Добавь его в .env файл.")
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.cascade_models = list(GEMINI_CASCADE_MODELS)
        self.active_model = self.cascade_models[0]  # По умолчанию gemini-3.8-flash
        self.quota_trackers = {m: QuotaTracker() for m in self.cascade_models}
        self.conversation_history: list[types.Content] = []
        logger.info(
            f"Gemini client инициализирован с каскадом: {', '.join(self.cascade_models)}. "
            f"Текущая активная модель: {self.active_model}"
        )

    def get_quota_status(self) -> dict:
        """Возвращает текущую статистику квоты активной модели и каскада."""
        active_tracker = self.quota_trackers.get(self.active_model) or next(iter(self.quota_trackers.values()))
        status = active_tracker.get_status()
        status["model"] = self.active_model
        status["provider"] = "gemini"
        status["cascade"] = self.get_cascade_status()
        return status

    def get_cascade_status(self) -> list[dict]:
        """Возвращает детальный статус всех ступеней каскада Gemini для UI."""
        priorities = {
            "gemini-3.8-flash": "Приоритет 1 (Основной)",
            "gemini-3.7-flash": "Резерв 1",
            "gemini-3.6-flash": "Резерв 2",
            "gemini-3.5-flash": "Резерв 3",
            "gemini-3-flash-preview": "Базовый порог (3.0)",
        }
        short_names = {
            "gemini-3.8-flash": "3.8 Flash",
            "gemini-3.7-flash": "3.7 Flash",
            "gemini-3.6-flash": "3.6 Flash",
            "gemini-3.5-flash": "3.5 Flash",
            "gemini-3-flash-preview": "3.0 Flash Preview",
        }
        res = []
        for m in self.cascade_models:
            tracker = self.quota_trackers.get(m)
            st = tracker.get_status() if tracker else {}
            res.append({
                "model": m,
                "name": short_names.get(m, m),
                "priority": priorities.get(m, "Резерв"),
                "rpm_limit": st.get("rpm_limit", 15),
                "rpm_remaining": st.get("rpm_remaining", 15),
                "rpm_used": st.get("rpm_used", 0),
                "rpd_limit": st.get("rpd_limit", 1500),
                "rpd_remaining": st.get("rpd_remaining", 1500),
                "rpd_used": st.get("rpd_used", 0),
                "reset_seconds": st.get("reset_seconds", 0),
                "is_active": (m == self.active_model),
            })
        return res

    def _parse_response(self, text: str) -> list[dict]:
        """Парсит JSON-ответ от Gemini, очищая от markdown-обёрток и лишнего текста."""
        cleaned = text.strip()
        match = re.search(r"(\[[\s\S]*\])", cleaned)
        if match:
            cleaned = match.group(1).strip()
        elif cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        try:
            result = json.loads(cleaned)
            if isinstance(result, list):
                return result
            return [result]
        except json.JSONDecodeError as e:
            logger.error(f"Не удалось распарсить ответ Gemini: {e}\nТекст: {cleaned}")
            return [{
                "action": "error",
                "params": {"message": f"Ошибка парсинга ответа: {str(e)}"},
                "description": "Ошибка обработки ответа от AI",
            }]

    async def _generate_with_cascade(
        self,
        contents: list,
        config: types.GenerateContentConfig,
        operation_name: str = "генерация",
    ) -> str:
        """
        Вызывает Gemini по строгой каскадной лестнице:
        gemini-3.8-flash -> gemini-3.7-flash -> gemini-3.6-flash -> gemini-3.5-flash -> gemini-3-flash-preview.
        Ниже 3.0 не опускается. При 429/503/исчерпании квоты автоматически переключается на следующую ступень.
        """
        last_error = None

        # Пробуем модели по порядку каскада
        for model_name in self.cascade_models:
            tracker = self.quota_trackers[model_name]
            st = tracker.get_status()

            # Если локальный трекер фиксирует исчерпание лимита RPM в текущую минуту, пропускаем
            if st["rpm_remaining"] <= 0:
                logger.info(f"Каскад Gemini: квота RPM для {model_name} исчерпана ({st['reset_seconds']}с до сброса). Спускаюсь ниже...")
                continue

            for attempt in range(2):
                try:
                    tracker.record_request()
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=config,
                    )
                    self.active_model = model_name
                    return response.text or ""
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    is_quota_or_load = (
                        "429" in err_str
                        or "503" in err_str
                        or "RESOURCE_EXHAUSTED" in err_str
                        or "UNAVAILABLE" in err_str
                        or "high demand" in err_str.lower()
                        or "quota" in err_str.lower()
                        or "404" in err_str
                    )

                    if is_quota_or_load:
                        logger.warning(
                            f"Каскад Gemini: модель {model_name} временно недоступна или исчерпала квоту ({err_str[:120]}). "
                            f"Переключаюсь на ступень ниже в каскаде..."
                        )
                        break  # Переход к следующей модели в cascade_models
                    else:
                        logger.error(f"Ошибка Gemini ({model_name}, {operation_name}): {e}")
                        if attempt == 0:
                            await asyncio.sleep(1.0)
                            continue
                        break

        raise RuntimeError(
            f"Все модели Gemini 3.x в каскаде исчерпали квоты или временно недоступны. "
            f"Ниже Gemini 3.0 спуск заблокирован. Последняя ошибка: {last_error}"
        )

    async def process_command(
        self,
        user_message: str,
        screenshot_base64: Optional[str] = None,
        playbook: Optional[dict] = None,
    ) -> list[dict]:
        """
        Обрабатывает команду пользователя через каскад моделей Gemini (3.8 -> 3.7 -> 3.6 -> 3.0).
        """
        parts: list[types.Part] = []

        if playbook:
            playbook_info = (
                f"[ПАМЯТЬ АГЕНТА] НАЙДЕН ЭТАЛОННЫЙ ШАБЛОН ДЛЯ БАЗОВОЙ ОПЕРАЦИИ:\n"
                f"Название сценария: {playbook.get('name')}\n"
                f"Базовые шаги:\n{json.dumps(playbook.get('actions', []), ensure_ascii=False, indent=2)}\n\n"
                f"ПРАВИЛО: Возьми этот сценарий за основу, НО если запрос пользователя шире базового добавления "
                f"(например, требует наполнить блок текстами под определенную тему, добавить кнопки, заголовок или подзаголовок), "
                f"ОБЯЗАТЕЛЬНО дополни сценарий действием edit_block_content с соответствующими текстами! Не оставляй блок пустым!"
            )
            parts.append(types.Part.from_text(text=playbook_info))

        if screenshot_base64:
            image_bytes = base64.b64decode(screenshot_base64)
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
            parts.append(types.Part.from_text(
                text=f"Текущее состояние браузера показано на скриншоте выше.\n\nКоманда пользователя: {user_message}"
            ))
        else:
            parts.append(types.Part.from_text(text=user_message))

        clean_history = []
        for content in self.conversation_history[-6:]:
            text_parts = [p for p in content.parts if getattr(p, "text", None) is not None]
            if text_parts:
                clean_history.append(types.Content(role=content.role, parts=text_parts))

        current_content = types.Content(role="user", parts=parts)
        send_contents = clean_history + [current_content]

        try:
            response_text = await self._generate_with_cascade(
                contents=send_contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                    max_output_tokens=4096,
                    response_mime_type="application/json",
                ),
                operation_name="process_command",
            )

            logger.info(f"Gemini ({self.active_model}) ответ: {response_text[:200]}...")

            self.conversation_history.append(current_content)
            self.conversation_history.append(
                types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=response_text)],
                )
            )

            return self._parse_response(response_text)

        except Exception as e:
            logger.error(f"Каскад Gemini завершился с ошибкой: {e}")
            return [{
                "action": "error",
                "params": {"message": f"Ошибка каскада Gemini: {str(e)}"},
                "description": f"Ошибка при обращении к Gemini: {str(e)}",
            }]

    # Псевдоним для совместимости
    plan_actions = process_command

    async def analyze_screenshot(self, screenshot_base64: str, question: str) -> str:
        """Анализирует скриншот через активную ступень каскада Gemini."""
        image_bytes = base64.b64decode(screenshot_base64)
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    types.Part.from_text(text=question),
                ],
            )
        ]
        try:
            return await self._generate_with_cascade(
                contents=contents,
                config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=2048),
                operation_name="analyze_screenshot",
            )
        except Exception as e:
            logger.error(f"Ошибка analyze_screenshot в Gemini: {e}")
            return f"Ошибка: {str(e)}"

    async def distill_golden_path(
        self,
        user_message: str,
        raw_actions: list[dict],
    ) -> list[dict]:
        """Дистиллирует чистый маршрут (Golden Path) через каскад Gemini."""
        prompt = f"""Ты — главный архитектор надёжной браузерной автоматизации Tilda.
Пользователь выполнил задачу: "{user_message}".
Вот действия, которые выполнялись (среди них могли быть лишние клики, промежуточные шаги, повторы):
{json.dumps(raw_actions, ensure_ascii=False, indent=2)}

Твоя задача:
1. Выдели САМЫЙ КОРОТКИЙ, ЧИСТЫЙ и БЕЗОПАСНЫЙ эталонный маршрут (Golden Path) для достижения ЭТОГО ЖЕ результата с первого раза.
2. Убери все лишние клики, промежуточные ожидания, дубли и костыли.
3. В конце обязательно добавь действие screenshot для фиксации результата.
4. Идеальный рецепт должен содержать от 2 до 5 простых и понятных шагов.

Доступные действия: navigate, click, fill, wait, screenshot, login, save_page, publish_page, open_project, open_page.

Ответь ТОЛЬКО валидным JSON-массивом действий без markdown и пояснений:
[
  {{"action": "...", "params": {{...}}, "description": "..."}}
]
"""
        try:
            response_text = await self._generate_with_cascade(
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                ),
                operation_name="distill_golden_path",
            )
            parsed = self._parse_response(response_text)
            if parsed and not (len(parsed) == 1 and parsed[0].get("action") == "error"):
                logger.info(f"[Маршрут] Golden Path успешно дистиллирован: {len(parsed)} шагов вместо {len(raw_actions)}")
                return parsed
        except Exception as e:
            logger.warning(f"Ошибка дистилляции Golden Path в Gemini: {e}")

        return []

    async def plan_recovery(
        self,
        user_goal: str,
        failed_action: dict,
        error_message: str,
        screenshot_base64: Optional[str] = None,
    ) -> list[dict]:
        """Генерирует корректирующие действия (Self-Healing) через каскад Gemini."""
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

        parts: list[types.Part] = []
        if screenshot_base64:
            image_bytes = base64.b64decode(screenshot_base64)
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
        parts.append(types.Part.from_text(text=recovery_prompt))

        try:
            response_text = await self._generate_with_cascade(
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                ),
                operation_name="plan_recovery",
            )
            actions = self._parse_response(response_text)
            if actions and not (len(actions) == 1 and actions[0].get("action") == "error"):
                logger.info(f"Self-Healing: Gemini предложил {len(actions)} корректирующих действий")
                return actions
        except Exception as e:
            logger.warning(f"Ошибка Gemini plan_recovery: {e}")

        return []

    async def generate_raw_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """Генерирует произвольный текст (например, точный CSS/JS код) через каскад Gemini."""
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
        )
        content = types.Content(role="user", parts=[types.Part.from_text(text=user_prompt)])
        return await self._generate_with_cascade(contents=[content], config=config, operation_name="генерация кода")

    def reset_history(self):
        """Сбрасывает историю диалога."""
        self.conversation_history.clear()
        logger.info("История диалога с Gemini сброшена.")
