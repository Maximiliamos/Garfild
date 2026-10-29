"""SQLite persistence for local notes, workflow definitions and execution logs."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class LocalStore:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created REAL NOT NULL,
                    content TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created REAL NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created REAL NOT NULL,
                    plan TEXT NOT NULL,
                    result TEXT NOT NULL
                );
            """)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5.0)
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def add_note(self, content: str) -> int:
        content = content.strip()
        if not content or len(content) > 4000:
            raise ValueError("Заметка должна содержать от 1 до 4000 символов")
        with self._lock, self._connect() as db:
            cur = db.execute("INSERT INTO notes(created, content) VALUES (?, ?)", (time.time(), content))
            return int(cur.lastrowid)

    def notes(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            if query:
                # Escape LIKE wildcards; no SQL string interpolation.
                escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                rows = db.execute("SELECT id, content FROM notes WHERE content LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT ?", (f"%{escaped}%", min(limit, 50))).fetchall()
            else:
                rows = db.execute("SELECT id, content FROM notes ORDER BY id DESC LIMIT ?", (min(limit, 50),)).fetchall()
        return [{"id": i, "content": text} for i, text in rows]

    def delete_note(self, identifier: int) -> bool:
        with self._lock, self._connect() as db:
            return db.execute("DELETE FROM notes WHERE id = ?", (int(identifier),)).rowcount > 0

    def add_message(self, role: str, text: str) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("Invalid message role")
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO conversations(created, role, text) VALUES (?, ?, ?)", (time.time(), role, text[:16000]))

    def search_messages(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT role, text FROM conversations WHERE text LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT ?", (f"%{escaped}%", min(limit, 30))).fetchall()
        return [{"role": role, "text": txt} for role, txt in rows]

    def record_run(self, steps: list[dict], results: list[dict]) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO executions(created, plan, result) VALUES (?, ?, ?)", (time.time(), json.dumps(steps, ensure_ascii=False), json.dumps(results, ensure_ascii=False)))
