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
                CREATE TABLE IF NOT EXISTS scheduled_runs (
                    workflow_id TEXT NOT NULL,
                    run_key TEXT NOT NULL,
                    claimed REAL NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (workflow_id, run_key)
                );
            """)
            # Existing installations predate the optional detail column.
            columns = {row[1] for row in db.execute("PRAGMA table_info(scheduled_runs)")}
            if "detail" not in columns:
                db.execute("ALTER TABLE scheduled_runs ADD COLUMN detail TEXT NOT NULL DEFAULT ''")
            db.execute(
                "CREATE INDEX IF NOT EXISTS scheduled_runs_filter_idx "
                "ON scheduled_runs(status, workflow_id, claimed DESC)"
            )
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

    def claim_scheduled_run(self, workflow_id: str, run_key: str) -> bool:
        """Atomically reserve an execution before running it.

        A claimed schedule is never automatically retried, including when the
        process crashes. This deliberately favors at-most-once execution.
        """
        if not workflow_id or len(workflow_id) > 40 or not run_key or len(run_key) > 100:
            raise ValueError("Invalid scheduled run identifier")
        with self._lock, self._connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO scheduled_runs(workflow_id, run_key, claimed, status) "
                "VALUES (?, ?, ?, ?)",
                (workflow_id, run_key, time.time(), "claimed"),
            )
            return cursor.rowcount == 1

    def claim_file_event_run(self, workflow_id: str) -> str:
        """Journal a detected file event; detection itself remains in-memory."""
        import uuid

        if not workflow_id or len(workflow_id) > 40:
            raise ValueError("Invalid workflow identifier")
        run_key = "file:" + uuid.uuid4().hex
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO scheduled_runs(workflow_id, run_key, claimed, status) "
                "VALUES (?, ?, ?, 'claimed')",
                (workflow_id, run_key, time.time()),
            )
        return run_key

    def finish_scheduled_run(
        self, workflow_id: str, run_key: str, success: bool, detail: str = ""
    ) -> None:
        with self._lock, self._connect() as db:
            updated = db.execute(
                "UPDATE scheduled_runs SET status = ?, detail = ? "
                "WHERE workflow_id = ? AND run_key = ? AND status = 'claimed'",
                ("succeeded" if success else "failed", self._seal(detail[:500]), workflow_id, run_key),
            )
            if updated.rowcount != 1:
                raise ValueError("Unknown or already completed scheduled run")

    @staticmethod
    def _scheduled_filters(
        status: str | None, workflow_id: str | None,
    ) -> tuple[str, list[str]]:
        if status not in (None, "claimed", "succeeded", "failed"):
            raise ValueError("Неверный фильтр состояния задания")
        if workflow_id is not None and (
            not isinstance(workflow_id, str) or len(workflow_id) > 40
            or not workflow_id or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
                                      for c in workflow_id)
        ):
            raise ValueError("Неверный идентификатор сценария")
        clauses: list[str] = []
        params: list[str] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if workflow_id is not None:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def count_scheduled_runs(
        self, *, status: str | None = None, workflow_id: str | None = None,
    ) -> int:
        where, params = self._scheduled_filters(status, workflow_id)
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM scheduled_runs" + where, params
            ).fetchone()
        return int(row[0])

    def list_scheduled_runs(
        self, limit: int = 50, *, status: str | None = None,
        workflow_id: str | None = None, offset: int = 0,
        review_after_sec: int = 1800, now: float | None = None,
    ) -> list[dict[str, Any]]:
        """Page through journal entries; never promote an old claim to failure.

        An old claimed record is only flagged as requiring investigation.
        It may still represent a running task, so automatic retry is unsafe.
        """
        limit = int(limit)
        offset = int(offset)
        if not 1 <= limit <= 200 or not 0 <= offset <= 100_000:
            raise ValueError("Неверный размер страницы или смещение")
        if not 60 <= review_after_sec <= 86_400:
            raise ValueError("Неверный порог проверки зависших заданий")
        where, params = self._scheduled_filters(status, workflow_id)
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT workflow_id, run_key, claimed, status, detail "
                "FROM scheduled_runs" + where +
                " ORDER BY claimed DESC, rowid DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        current_time = time.time() if now is None else float(now)
        return [
            {
                "workflow_id": workflow_id, "run_key": run_key,
                "claimed": float(claimed), "status": state,
                "detail": self._unseal(detail),
                "needs_review": (
                    state == "claimed" and current_time - float(claimed) >= review_after_sec
                ),
            }
            for workflow_id, run_key, claimed, state, detail in rows
        ]

    def latest_scheduled_run(self, workflow_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT workflow_id, run_key, claimed, status, detail "
                "FROM scheduled_runs WHERE workflow_id = ? "
                "ORDER BY claimed DESC, rowid DESC LIMIT 1",
                (workflow_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "workflow_id": row[0], "run_key": row[1], "claimed": float(row[2]),
            "status": row[3], "detail": self._unseal(row[4]),
        }

    def scheduled_run_status(self, workflow_id: str, run_key: str) -> str | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT status FROM scheduled_runs WHERE workflow_id = ? AND run_key = ?",
                (workflow_id, run_key),
            ).fetchone()
            return row[0] if row else None

    def record_run(self, steps: list[dict], results: list[dict]) -> None:
        plan = json.dumps(steps, ensure_ascii=False)
        output = json.dumps(results, ensure_ascii=False)
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO executions(created, plan, result) VALUES (?, ?, ?)",
                       (time.time(), self._seal(plan), self._seal(output)))
