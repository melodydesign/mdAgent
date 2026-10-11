"""
mdAgent — Memory & Playbooks Manager
Модуль долговременной памяти: хранение, поиск, самообучение и повторное использование
проверенных цепочек действий для Tilda.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
PLAYBOOKS_FILE = DATA_DIR / "playbooks.json"


# Базовые встроенные рецепты для типовых операций в Tilda
BUILTIN_PLAYBOOKS = [
    {
        "id": "builtin_create_and_fill_cover",
        "name": "Выбор обложки с 2 кнопками и наполнение контентом",
        "intent_keywords": [
            "блок обложки", "обложка с 2 кнопками", "обложка две кнопки", "обложку с двумя кнопками",
            "обложка заголовок подзаголовок", "обложка 2 кнопки", "hero блок", "обложка с кнопками",
            "обложки подходящий", "блок обложки подходящий"
        ],
        "description": "Поиск и выбор блока обложки с 2 кнопками в библиотеке и заполнение заголовка, подзаголовка и кнопок",
        "actions": [
            {
                "action": "browse_and_select_block",
                "params": {
                    "category": "Обложка",
                    "requirements": "заголовок, подзаголовок, 2 кнопки"
                },
                "description": "Ищу и выбираю в категории «Обложка» блок с 2 кнопками, заголовком и подзаголовком"
            },
            {
                "action": "edit_block_content",
                "params": {
                    "title": "Заголовок обложки",
                    "descr": "Подзаголовок и краткое описание предложения",
                    "btn_text": "Основное действие",
                    "btn_href": "#start",
                    "btn2_text": "Подробнее",
                    "btn2_href": "#info",
                    "img_url": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1600&q=80"
                },
                "description": "Заполняю заголовок, подзаголовок, две кнопки и фоновое изображение через панель «Контент»"
            },
            {"action": "screenshot", "params": {}, "description": "Фиксирую готовый блок обложки"}
        ],
        "success_count": 25,
        "failure_count": 0,
        "is_builtin": True,
        "created_at": 1710000000,
        "last_used": 1710000000,
    },
    {
        "id": "builtin_add_block",
        "name": "Добавление блока на страницу (T123, Zero и др.)",
        "intent_keywords": ["создай блок", "добавь блок", "добавить блок", "новый блок", "блок t123", "блок zero", "вставить блок", "add block", "блок html", "блок на странице", "создать блок"],
        "description": "Добавление блока из библиотеки Tilda на страницу",
        "actions": [
            {"action": "add_block", "params": {"code": "T123"}, "description": "Добавляю блок T123 (HTML-код)"},
            {"action": "screenshot", "params": {}, "description": "Фиксирую добавленный блок"}
        ],
        "success_count": 15,
        "failure_count": 0,
        "is_builtin": True,
        "created_at": 1710000000,
        "last_used": 1710000000,
    },
    {
        "id": "builtin_create_project",
        "name": "Создание нового сайта (проекта)",
        "intent_keywords": ["создай сайт", "создать сайт", "новый сайт", "создай проект", "создать проект", "create site", "create project", "новый проект"],
        "description": "Создание нового сайта в Tilda",
        "actions": [
            {"action": "create_project", "params": {"name": "Мой сайт"}, "description": "Создаю новый сайт в Tilda"},
            {"action": "screenshot", "params": {}, "description": "Фиксирую созданный проект"}
        ],
        "success_count": 10,
        "failure_count": 0,
        "is_builtin": True,
        "created_at": 1710000000,
        "last_used": 1710000000,
    },
    {
        "id": "builtin_open_projects",
        "name": "Переход к списку проектов",
        "intent_keywords": ["проекты", "мои проекты", "список проектов", "админка", "главная", "projects", "show projects"],
        "description": "Открывает панель со списком всех сайтов",
        "actions": [
            {"action": "navigate", "params": {"url": "https://tilda.cc/projects/"}, "description": "Открываю панель проектов Tilda"},
            {"action": "screenshot", "params": {}, "description": "Фиксирую список проектов"}
        ],
        "success_count": 12,
        "failure_count": 0,
        "is_builtin": True,
        "created_at": 1710000000,
        "last_used": 1710000000,
    },
    {
        "id": "builtin_create_page",
        "name": "Создание новой страницы",
        "intent_keywords": ["создай страницу", "создать страницу", "новая страница", "добавить страницу", "create page", "new page"],
        "description": "Создание новой страницы в текущем проекте",
        "actions": [
            {"action": "create_page", "params": {"title": "Новая страница"}, "description": "Создаю новую страницу в проекте"},
            {"action": "screenshot", "params": {}, "description": "Фиксирую созданную страницу"}
        ],
        "success_count": 8,
        "failure_count": 0,
        "is_builtin": True,
        "created_at": 1710000000,
        "last_used": 1710000000,
    },
    {
        "id": "builtin_page_seo",
        "name": "Настройка SEO страницы (Title и Description)",
        "intent_keywords": ["настройки страницы", "seo", "тайтл", "дескрипшен", "заголовок страницы", "page title", "description", "название страницы"],
        "description": "Настройка параметров Title и Description страницы",
        "actions": [
            {"action": "set_page_seo", "params": {"title": "Главная", "description": "Описание сайта"}, "description": "Настраиваю SEO параметры страницы"},
            {"action": "screenshot", "params": {}, "description": "Фиксирую настройки страницы"}
        ],
        "success_count": 6,
        "failure_count": 0,
        "is_builtin": True,
        "created_at": 1710000000,
        "last_used": 1710000000,
    },
    {
        "id": "builtin_delete_project",
        "name": "Удаление проекта (сайта)",
        "intent_keywords": ["удали сайт", "удалить сайт", "удали проект", "удалить проект", "delete site", "delete project"],
        "description": "Удаление проекта из панели Tilda",
        "actions": [
            {"action": "delete_project", "params": {}, "description": "Удаляю выбранный сайт"},
            {"action": "screenshot", "params": {}, "description": "Фиксирую результат удаления"}
        ],
        "success_count": 5,
        "failure_count": 0,
        "is_builtin": True,
        "created_at": 1710000000,
        "last_used": 1710000000,
    },
    {
        "id": "builtin_save_page",
        "name": "Сохранение текущей страницы",
        "intent_keywords": ["сохрани", "сохранить страницу", "сохранить", "save page", "save"],
        "description": "Быстрое сохранение изменений страницы",
        "actions": [
            {"action": "save_page", "params": {}, "description": "Сохраняю страницу (Ctrl+S)"},
            {"action": "screenshot", "params": {}, "description": "Скриншот после сохранения"}
        ],
        "success_count": 8,
        "failure_count": 0,
        "is_builtin": True,
        "created_at": 1710000000,
        "last_used": 1710000000,
    },
    {
        "id": "builtin_publish_page",
        "name": "Публикация текущей страницы",
        "intent_keywords": ["опубликуй", "опубликовать", "опубликовать страницу", "publish", "publish page"],
        "description": "Публикация страницы в открытый доступ",
        "actions": [
            {"action": "publish_page", "params": {}, "description": "Нажимаю кнопку 'Опубликовать'"},
            {"action": "screenshot", "params": {}, "description": "Скриншот после публикации"}
        ],
        "success_count": 4,
        "failure_count": 0,
        "is_builtin": True,
        "created_at": 1710000000,
        "last_used": 1710000000,
    }
]


def _stem_word(word: str) -> str:
    """Упрощенный стеммер русских и английских слов для устойчивого поиска интентов."""
    w = word.lower().strip()
    if len(w) <= 3:
        return w
    for ending in ("ями", "ами", "ей", "ов", "ев", "ой", "ем", "ом", "ах", "ях", "ую", "юю", "ые", "ие", "ый", "ий", "а", "я", "о", "е", "у", "ю", "ы", "и"):
        if w.endswith(ending) and len(w) - len(ending) >= 3:
            return w[:-len(ending)]
    return w


class MemoryManager:
    """Управление базой знаний и проверенных рецептов действий."""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.playbooks: list[dict] = []
        self._load()

    def _load(self):
        """Загружает базу навыков из JSON или инициализирует базовыми."""
        if PLAYBOOKS_FILE.exists():
            try:
                data = json.loads(PLAYBOOKS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.playbooks = data
                    existing_ids = {p.get("id") for p in self.playbooks}
                    needs_save = False
                    for b in BUILTIN_PLAYBOOKS:
                        if b["id"] not in existing_ids:
                            self.playbooks.insert(0, b)
                            needs_save = True
                    if needs_save:
                        self._save()
                    logger.info(f"Загружено {len(self.playbooks)} навыков из памяти")
                    return
            except Exception as e:
                logger.error(f"Ошибка загрузки памяти playbooks.json: {e}")

        # Если файла нет или он поврежден — стартуем со встроенных
        self.playbooks = list(BUILTIN_PLAYBOOKS)
        self._save()

    def _save(self):
        """Атомарно сохраняет базу навыков на диск."""
        try:
            temp_file = PLAYBOOKS_FILE.with_suffix(".tmp")
            temp_file.write_text(
                json.dumps(self.playbooks, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            temp_file.replace(PLAYBOOKS_FILE)
        except Exception as e:
            logger.error(f"Не удалось сохранить playbooks.json: {e}")

    def find_playbook(self, query: str) -> Optional[dict]:
        """
        Ищет наиболее подходящий проверенный сценарий для запроса.
        Использует сопоставление ключевых фраз и стемминг корней слов для работы с любыми падежами.
        """
        cleaned_query = query.lower().strip()
        query_words = [w for w in re.split(r"\W+", cleaned_query) if w]
        query_stems = {_stem_word(w) for w in query_words}

        best_match = None
        best_score = 0.0

        is_block_query = any(k in cleaned_query for k in ["блок", "block", "t123", "zero", "html", "обложк"])
        is_content_filling_query = any(k in cleaned_query for k in [
            "заголовок", "подзаголовок", "кнопк", "наполни", "тему", "описани", "текст",
            "контент", "замен", "поменяй", "измени", "отредактир", "рутин", "платформ"
        ])
        is_edit_query = any(k in cleaned_query for k in ["замен", "поменяй", "измени", "отредактир", "контент", "текст"])

        for playbook in self.playbooks:
            # Защита от ложного срабатывания: запросы о блоках не должны сопоставляться с созданием сайта
            if is_block_query and playbook.get("id") == "builtin_create_project":
                continue

            # Если запрос требует замены или наполнения контента, примитивный 2-шаговый add_block не должен его перехватывать
            if (is_content_filling_query or is_edit_query) and playbook.get("id") == "builtin_add_block":
                continue

            score = 0.0
            keywords = playbook.get("intent_keywords", [])

            for kw in keywords:
                kw_clean = kw.lower()
                # 1. Прямое вхождение подстроки
                if kw_clean in cleaned_query:
                    match_ratio = len(kw_clean) / max(len(cleaned_query), 1)
                    score = max(score, 0.85 + 0.15 * match_ratio)
                else:
                    # 2. Стеммированное сопоставление корней слов
                    kw_words = [w for w in re.split(r"\W+", kw_clean) if len(w) >= 2 or w.isdigit()]
                    if kw_words:
                        kw_stems = [_stem_word(w) for w in kw_words]
                        matches = sum(1 for s in kw_stems if s in query_stems or any(s in qs for qs in query_stems))
                        word_score = matches / len(kw_stems)
                        if word_score >= 0.6:
                            score = max(score, 0.75 * word_score)

            # Бонус за популярность и надежность
            successes = playbook.get("success_count", 0)
            failures = playbook.get("failure_count", 0)
            total = successes + failures
            if total > 0:
                reliability = successes / total
                score *= (0.85 + 0.15 * reliability)

            if score > best_score and score >= 0.5:
                best_score = score
                best_match = playbook

        if best_match:
            logger.info(f"[Память] Найдено соответствие: '{best_match['name']}' (score: {best_score:.2f})")
        return best_match

    def sanitize_actions(self, actions: list[dict]) -> list[dict]:
        """
        Алгоритмически очищает сырой лог действий:
        1. Отбрасывает действия с success=False, error, clarify.
        2. Удаляет подряд идущие дубликаты.
        3. Удаляет промежуточные скриншоты, оставляя только финальный.
        """
        clean = []
        for a in actions:
            if a.get("success") is False:
                continue
            act_name = a.get("action")
            if act_name in ("error", "clarify", "busy", "unknown", None):
                continue

            act_params = dict(a.get("params", {}))
            if act_name in ("edit_block_content", "edit_block_settings", "swap_block_title_descr") and act_params.get("block_id"):
                # Очищаем конкретный ID блока, чтобы навык оставался универсальным для любых страниц
                act_params["block_id"] = ""

            clean.append({
                "action": act_name,
                "params": act_params,
                "description": a.get("description", act_name)
            })

        # Убираем дубликаты подряд
        deduped = []
        prev = None
        for a in clean:
            key = (a.get("action"), json.dumps(a.get("params", {}), sort_keys=True))
            if key != prev:
                deduped.append(a)
                prev = key

        # Оставляем только финальный скриншот
        final_actions = []
        total_screenshots = sum(1 for a in deduped if a.get("action") == "screenshot")
        screenshots_seen = 0
        for a in deduped:
            if a.get("action") == "screenshot":
                screenshots_seen += 1
                if screenshots_seen == total_screenshots:
                    final_actions.append(a)
            else:
                final_actions.append(a)

        # Гарантируем наличие скриншота в конце если его не было
        if final_actions and final_actions[-1].get("action") != "screenshot":
            final_actions.append({
                "action": "screenshot",
                "params": {},
                "description": "Фиксация результата"
            })

        return final_actions

    def learn_from_execution(
        self,
        user_message: str,
        actions: list[dict],
        description: Optional[str] = None
    ) -> Optional[dict]:
        """
        Обучение: сохраняет идеальную цепочку действий как новый проверенный рецепт.
        """
        clean_actions = self.sanitize_actions(actions)

        # Фильтруем тривиальные цепочки
        if not clean_actions or (len(clean_actions) == 1 and clean_actions[0].get("action") == "screenshot"):
            return None

        # ─── Memory Guard 1: Запрет сохранения сценариев без реальных мутирующих действий ───
        mutating_actions = {
            "add_block", "browse_and_select_block", "edit_block_content", "swap_block_title_descr", "edit_block_settings",
            "edit_t123_code", "delete_block", "clear_page", "duplicate_block", "hide_block", "move_block_up", "move_block_down",
            "create_project", "delete_project", "create_page", "set_page_seo", "publish_page"
        }
        # Исключаем publish_page из цепочки если пользователь прямо не требовал публикации
        msg_lower = user_message.lower()
        if not any(w in msg_lower for w in ("опубликуй", "публикуй", "publish", "опубликовать")):
            clean_actions = [a for a in clean_actions if a.get("action") != "publish_page"]

        has_mutation = any(a.get("action") in mutating_actions for a in clean_actions)
        if not has_mutation:
            logger.info(f"[Память Guard] Пропуск сохранения: сценарий не содержит мутирующих действий ({[a.get('action') for a in clean_actions]})")
            return None

        # ─── Memory Guard 2: Фильтрация вопросов, инспекций и диалоговых реплик ───
        msg_clean = user_message.lower().strip()
        question_prefixes = (
            "ну дак", "почему", "разве", "как ", "что ", "проверь", "посмотри",
            "скажи", "где ", "зачем", "а ", "но "
        )
        if msg_clean.endswith("?") or any(msg_clean.startswith(p) for p in question_prefixes) or "разве не" in msg_clean:
            logger.info(f"[Память Guard] Пропуск сохранения: запрос пользователя является вопросом/проверкой («{user_message}»)")
            return None

        # ─── Memory Guard 3: Запрет сохранения одноразовых команд удаления конкретных блоков ───
        is_delete_block_cmd = any(a.get("action") == "delete_block" for a in clean_actions)
        has_delete_intent = any(w in msg_clean for w in ("удали блок", "удалить блок", "delete block", "найди и удали"))
        if is_delete_block_cmd or has_delete_intent:
            logger.info(f"[Память Guard] Пропуск сохранения: одноразовая операция удаления блока («{user_message}»)")
            return None

        # ─── Memory Guard 4: Запрет сохранения сценариев с пустым или шаблонным кодом T123 ───
        for a in clean_actions:
            if a.get("action") == "edit_t123_code":
                code_val = a.get("params", {}).get("code", "")
                if len(code_val.strip()) < 100 or ("/*" in code_val and "*/" in code_val and len(code_val.strip()) < 300):
                    logger.info("[Память Guard] Пропуск сохранения: блок T123 содержит шаблонный комментарий без реального кода")
                    return None

        # 1. Проверяем текстовое совпадение с уже известным сценарием
        existing = self.find_playbook(user_message)
        if existing:
            existing["success_count"] = existing.get("success_count", 0) + 1
            existing["last_used"] = int(time.time())
            self._save()
            logger.info(f"[Память] Обновлен существующий навык: '{existing['name']}' (успехов: {existing['success_count']})")
            return existing

        # 2. Дедупликация по сигнатуре действий (Action Fingerprint)
        def _get_sig(acts):
            return [(a.get("action"), str(a.get("params", {}).get("code") or a.get("params", {}).get("category") or "")) for a in acts if a.get("action") != "screenshot"]

        new_sig = _get_sig(clean_actions)
        if new_sig:
            for p in self.playbooks:
                if _get_sig(p.get("actions", [])) == new_sig:
                    # Навык с такой же последовательностью действий уже существует! Не создаем дубликат.
                    clean_kw = user_message.lower().strip()
                    if clean_kw not in p.get("intent_keywords", []):
                        p.setdefault("intent_keywords", []).append(clean_kw)
                    p["success_count"] = p.get("success_count", 0) + 1
                    p["last_used"] = int(time.time())
                    self._save()
                    logger.info(f"[Память] Синоним «{clean_kw}» добавлен к существующему навыку '{p['name']}' (дубликат предотвращён)")
                    return p

        # 3. Создаем новый playbook только если это действительно уникальный сценарий
        keywords = [
            user_message.lower().strip(),
            re.sub(r"[^\w\s]", "", user_message.lower()).strip()
        ]

        playbook_id = f"learned_{int(time.time())}_{len(self.playbooks)}"
        name = description or (user_message[:40] + ("..." if len(user_message) > 40 else ""))

        new_playbook = {
            "id": playbook_id,
            "name": name.capitalize(),
            "intent_keywords": list(set(k for k in keywords if k)),
            "description": f"Автоматически изученный сценарий для: {user_message}",
            "actions": clean_actions,
            "success_count": 1,
            "failure_count": 0,
            "is_builtin": False,
            "created_at": int(time.time()),
            "last_used": int(time.time()),
        }

        self.playbooks.append(new_playbook)
        self._save()
        logger.info(f"🎉 Изучен новый уникальный навык: '{new_playbook['name']}' ({len(clean_actions)} шагов)")
        return new_playbook

    def record_feedback(self, playbook_id: str, success: bool):
        """Записывает успех или неудачу выполнения сценария."""
        for p in self.playbooks:
            if p["id"] == playbook_id:
                if success:
                    p["success_count"] = p.get("success_count", 0) + 1
                else:
                    p["failure_count"] = p.get("failure_count", 0) + 1
                p["last_used"] = int(time.time())
                self._save()
                break

    def get_all(self) -> list[dict]:
        """Возвращает все сценарии, отсортированные по популярности."""
        return sorted(
            self.playbooks,
            key=lambda x: (x.get("success_count", 0), x.get("last_used", 0)),
            reverse=True
        )
