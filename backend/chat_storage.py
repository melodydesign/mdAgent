"""
mdAgent — Multi-Session Chat & Credentials Storage
Хранилище сессий диалогов и истории сообщений с поддержкой персистентности на диске.
Позволяет пользователю создавать несколько диалогов, переключаться между ними,
удалять, переименовывать, а также привязывать индивидуальные учетные данные Tilda
(email и пароль) к конкретному диалогу.
"""

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any

from backend.config import DATA_DIR

logger = logging.getLogger(__name__)

SESSIONS_FILE: Path = DATA_DIR / "chat_sessions.json"
LEGACY_CHAT_FILE: Path = DATA_DIR / "chat_history.json"


class ChatStorage:
    """Управляет сохранением сессий и чтением истории чата."""

    def __init__(self, file_path: Optional[Path] = None, max_messages: int = 400):
        self.file_path = file_path or SESSIONS_FILE
        self.max_messages = max_messages
        self._active_session_id: str = "default"
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        """Загружает сессии и сообщения из файла JSON, либо мигрирует legacy chat_history."""
        try:
            if self.file_path.exists():
                content = self.file_path.read_text(encoding="utf-8")
                data = json.loads(content)
                if isinstance(data, dict):
                    self._active_session_id = data.get("active_session_id", "default")
                    raw_sessions = data.get("sessions", [])
                    if isinstance(raw_sessions, list):
                        for s in raw_sessions:
                            sid = s.get("id") or str(uuid.uuid4())[:8]
                            s["messages"] = s.get("messages", [])[-self.max_messages:]
                            self._sessions[sid] = s
                    if self._sessions:
                        if self._active_session_id not in self._sessions:
                            self._active_session_id = next(iter(self._sessions.keys()))
                        logger.info(f"Загружено {len(self._sessions)} сессий из {self.file_path}")
                        return
        except Exception as e:
            logger.error(f"Ошибка загрузки сессий из {self.file_path}: {e}")

        # Миграция из legacy chat_history.json
        legacy_messages = []
        if LEGACY_CHAT_FILE.exists():
            try:
                legacy_content = LEGACY_CHAT_FILE.read_text(encoding="utf-8")
                legacy_data = json.loads(legacy_content)
                if isinstance(legacy_data, list):
                    legacy_messages = legacy_data[-self.max_messages:]
            except Exception as le:
                logger.warning(f"Не удалось прочитать legacy chat_history.json: {le}")

        default_session = {
            "id": "default",
            "title": "Основной диалог",
            "created_at": time.time(),
            "updated_at": time.time(),
            "tilda_email": "",
            "tilda_password": "",
            "messages": legacy_messages,
        }
        self._active_session_id = "default"
        self._sessions = {"default": default_session}
        self._save()

    def _save(self):
        """Сохраняет структуру всех сессий на диск."""
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            sessions_list = []
            for s in self._sessions.values():
                s_copy = dict(s)
                s_copy["messages"] = s_copy.get("messages", [])[-self.max_messages:]
                sessions_list.append(s_copy)

            payload = {
                "active_session_id": self._active_session_id,
                "sessions": sessions_list,
            }
            self.file_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Ошибка сохранения сессий в {self.file_path}: {e}")

    # ─────────────────────────── Управление сессиями ───────────────────────────

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Возвращает список всех сессий (без полных текстов сообщений)."""
        result = []
        for s in self._sessions.values():
            result.append({
                "id": s["id"],
                "title": s.get("title", "Диалог"),
                "created_at": s.get("created_at", 0),
                "updated_at": s.get("updated_at", 0),
                "messages_count": len(s.get("messages", [])),
                "is_active": s["id"] == self._active_session_id,
                "tilda_email": s.get("tilda_email", ""),
                "has_tilda_password": bool(s.get("tilda_password")),
            })
        result.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
        return result

    def get_active_session_id(self) -> str:
        """Возвращает ID активной сессии."""
        return self._active_session_id

    def get_active_session(self) -> Dict[str, Any]:
        """Возвращает данные активной сессии."""
        if self._active_session_id not in self._sessions:
            if not self._sessions:
                self.create_session("Основной диалог")
            else:
                self._active_session_id = next(iter(self._sessions.keys()))
        return self._sessions[self._active_session_id]

    def create_session(
        self,
        title: str = "Новый диалог",
        tilda_email: str = "",
        tilda_password: str = ""
    ) -> Dict[str, Any]:
        """Создает новую сессию диалога и делает её активной."""
        session_id = f"sess_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        now = time.time()
        new_session = {
            "id": session_id,
            "title": title.strip() or "Новый диалог",
            "created_at": now,
            "updated_at": now,
            "tilda_email": tilda_email.strip(),
            "tilda_password": tilda_password.strip(),
            "messages": [],
        }
        self._sessions[session_id] = new_session
        self._active_session_id = session_id
        self._save()
        logger.info(f"Создана новая сессия диалога '{new_session['title']}' ({session_id})")
        return new_session

    def select_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Переключает активную сессию."""
        if session_id in self._sessions:
            self._active_session_id = session_id
            self._save()
            logger.info(f"Переключена активная сессия на '{session_id}'")
            return self._sessions[session_id]
        return None

    def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
        tilda_email: Optional[str] = None,
        tilda_password: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Обновляет метаданные сессии (название, учетные данные Tilda)."""
        if session_id in self._sessions:
            s = self._sessions[session_id]
            if title is not None:
                s["title"] = title.strip() or s["title"]
            if tilda_email is not None:
                s["tilda_email"] = tilda_email.strip()
            if tilda_password is not None:
                s["tilda_password"] = tilda_password.strip()
            s["updated_at"] = time.time()
            self._save()
            return s
        return None

    def delete_session(self, session_id: str) -> bool:
        """Удаляет сессию. Если удалена активная — переключает на другую."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            if not self._sessions:
                self.create_session("Основной диалог")
            elif self._active_session_id == session_id:
                self._active_session_id = next(iter(self._sessions.keys()))
            self._save()
            logger.info(f"Удалена сессия '{session_id}'")
            return True
        return False

    def get_tilda_credentials(self) -> tuple[Optional[str], Optional[str]]:
        """Возвращает (email, password) для активной сессии, если они заданы."""
        active = self.get_active_session()
        email = active.get("tilda_email") or None
        pwd = active.get("tilda_password") or None
        return email, pwd

    # ─────────────────────────── Сообщения активной сессии ───────────────────────────

    def add_message(
        self,
        role: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Добавляет сообщение в текущую активную сессию."""
        active = self.get_active_session()
        msg = {
            "id": f"msg_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}",
            "role": role,
            "text": text.strip(),
            "timestamp": time.time(),
            "time_str": time.strftime("%H:%M:%S", time.localtime()),
            "metadata": metadata or {},
        }
        active.setdefault("messages", []).append(msg)
        active["updated_at"] = time.time()
        self._save()
        return msg

    def get_messages(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Возвращает историю сообщений активной сессии."""
        active = self.get_active_session()
        msgs = active.get("messages", [])
        if limit and limit > 0:
            return msgs[-limit:]
        return list(msgs)

    def clear(self) -> bool:
        """Очищает историю сообщений активной сессии."""
        active = self.get_active_session()
        active["messages"] = []
        active["updated_at"] = time.time()
        self._save()
        logger.info(f"История сообщений сессии '{self._active_session_id}' очищена")
        return True
