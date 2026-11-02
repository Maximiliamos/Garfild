"""SQLite persistence with automatic Windows DPAPI-at-rest protection.

On Windows, notes, message text and execution logs are DPAPI-protected for the
current Windows user. This is not portable encryption, shared-device protection
against the same logged-in user, or cross-device sync. On non-Windows platforms
SQLite remains plaintext; do not store secrets.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .secrets import PREFIX, protect, reveal


class LocalStore:
    def __init__(self, path: Path, encrypt_at_rest: bool | None = None):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.encrypt_at_rest = (os.name == "nt") if encrypt_at_rest is None else encrypt_at_rest
        if self.encrypt_at_rest and os.name != "nt":
            raise RuntimeError("DPAPI-защита памяти работает только в Windows")
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
        if self.encrypt_at_rest:
            self._migrate_legacy()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5.0)
        db.execute("PRAGMA busy_timeout = 5000")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _seal(self, value: str) -> str:
        return protect(value) if self.encrypt_at_rest else value

    def _unseal(self, value: str) -> str:
        return reveal(value)

    def _migrate_legacy(self) -> None:
        """Convert legacy plaintext rows, and reclaim free pages after migration."""
        changed = False
        with self._lock, self._connect() as db:
            for table, columns in (
                ("notes", ("content",)),
                ("conversations", ("text",)),
                ("executions", ("plan", "result")),
            ):
                rows = db.execute(f"SELECT id, {', '.join(columns)} FROM {table}").fetchall()
                for row in rows:
                    values = list(row[1:])
                    if not any(value and not value.startswith(PREFIX) for value in values):
                        continue
                    sealed = [self._seal(value) for value in values]
                    assignments = ", ".join(f"{column} = ?" for column in columns)
                    db.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", (*sealed, row[0]))
                    changed = True
        if changed:
            # SQLite VACUUM cannot erase pre-existing OS snapshots or backups.
            with self._lock, self._connect() as db:
                db.execute("VACUUM")

    def add_note(self, content: str) -> int:
        content = content.strip()
        if not content or len(content) > 4000:
            raise ValueError("Заметка должна содержать от 1 до 4000 символов")
        with self._lock, self._connect() as db:
            cur = db.execute("INSERT INTO notes(created, content) VALUES (?, ?)",
                             (time.time(), self._seal(content)))
            return int(cur.lastrowid)

    def notes(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        # Encrypted SQLite cannot use LIKE; filter in memory after decrypting.
        limit = max(1, min(int(limit), 50))
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT id, content FROM notes ORDER BY id DESC").fetchall()
        matched = []
        for identifier, ciphertext in rows:
            plaintext = self._unseal(ciphertext)
            if query.casefold() in plaintext.casefold():
                matched.append({"id": identifier, "content": plaintext})
                if len(matched) >= limit:
                    break
        return matched

    def delete_note(self, identifier: int) -> bool:
        with self._lock, self._connect() as db:
            return db.execute("DELETE FROM notes WHERE id = ?", (int(identifier),)).rowcount > 0

    def _clear_table(self, table: str) -> int:
        # Internal allowlist; table name cannot be supplied by a user/LLM.
        if table not in {"notes", "conversations"}:
            raise ValueError("Invalid local table")
        with self._lock:
            with self._connect() as db:
                deleted = db.execute(f"DELETE FROM {table}").rowcount
            if deleted:
                # Rebuild free pages. Backups/OS snapshots are not erased by VACUUM.
                with self._connect() as db:
                    db.execute("VACUUM")
        return int(deleted)

    def clear_saved_history(self) -> int:
        return self._clear_table("conversations")

    def clear_all_notes(self) -> int:
        return self._clear_table("notes")

    def add_message(self, role: str, text: str) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("Invalid message role")
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO conversations(created, role, text) VALUES (?, ?, ?)",
                       (time.time(), role, self._seal(text[:16000])))

    def search_messages(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 30))
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT role, text FROM conversations ORDER BY id DESC LIMIT 2000").fetchall()
        matched = []
        for role, ciphertext in rows:
            plaintext = self._unseal(ciphertext)
            if query.casefold() in plaintext.casefold():
                matched.append({"role": role, "text": plaintext})
                if len(matched) >= limit:
                    break
        return matched

    def record_run(self, steps: list[dict], results: list[dict]) -> None:
        plan = json.dumps(steps, ensure_ascii=False)
        output = json.dumps(results, ensure_ascii=False)
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO executions(created, plan, result) VALUES (?, ?, ?)",
                       (time.time(), self._seal(plan), self._seal(output)))
