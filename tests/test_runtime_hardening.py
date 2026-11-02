"""Regression coverage for crash review, retention and runtime extraction."""
from __future__ import annotations

import ast
import os
import sqlite3
import tempfile
import threading
import time
import types
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from garfield_agent.controller import AgentController
from garfield_agent.storage import LocalStore
from garfield_runtime.schedule_health import describe_claim, process_identity
from garfield_runtime.scheduler import run_one_job


class OwnerAndRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = LocalStore(self.root / "store.sqlite3")

    def claim(self, key, state=None, *, days_ago=1):
        self.store.claim_scheduled_run("checks", key, owner_session="session-A", owner_pid=os.getpid())
        with self.store._lock, self.store._connect() as db:
            db.execute(
                "UPDATE scheduled_runs SET claimed = ?, heartbeat = ? WHERE run_key = ?",
                (time.time() - days_ago * 86400, time.time() - days_ago * 86400, key),
            )
        if state:
            self.store.finish_scheduled_run("checks", key, state == "succeeded", "done")

    def test_retention_excludes_claimed_and_recent_rows(self):
        self.claim("daily:old-success", "succeeded", days_ago=200)
        self.claim("daily:old-failure", "failed", days_ago=150)
        self.claim("daily:active", days_ago=400)
        self.claim("daily:recent-success", "succeeded", days_ago=2)
        preview = self.store.retention_preview(90)
        self.assertEqual(preview["count"], 2)
        deleted = self.store.prune_scheduled_runs(preview["cutoff"])
        self.assertEqual(deleted, 2)
        self.assertEqual(self.store.scheduled_run_status("checks", "daily:active"), "claimed")
        self.assertEqual(self.store.scheduled_run_status("checks", "daily:recent-success"), "succeeded")
        self.assertEqual(self.store.count_scheduled_runs(), 2)

    def test_invalid_retention_period_and_cutoff(self):
        for days in (0, -1, 3651):
            with self.assertRaises(ValueError):
                self.store.retention_preview(days)
        with self.assertRaises(ValueError):
            self.store.prune_scheduled_runs(time.time() + 1000)

    def test_cleanup_two_phase_confirmation_and_expiry(self):
        controller = AgentController(
            self.root, lambda: None, threading.Event(),
            self.root / "controller-db", self.root / "workspace",
        )
        store = controller.store
        store.claim_scheduled_run("checks", "old")
        with store._lock, store._connect() as db:
            db.execute("UPDATE scheduled_runs SET claimed = ? WHERE run_key = 'old'",
                       (time.time() - 120 * 86400,))
        store.finish_scheduled_run("checks", "old", True)
        self.assertIn("Нет подтверждённого", controller.handle("подтверди очистку журнала"))
        self.assertEqual(store.count_scheduled_runs(), 1)
        self.assertIn("Удалению подлежат 1", controller.handle("очисти журнал старше 90 дней"))
        self.assertIn("отменена", controller.handle("отмени очистку журнала"))
        self.assertEqual(store.count_scheduled_runs(), 1)
        controller.handle("очисти журнал старше 90 дней")
        controller._pending_retention = (controller._pending_retention[0], time.monotonic() - 125)
        self.assertIn("Нет подтверждённого", controller.handle("подтверди очистку журнала"))
        controller.handle("очисти журнал старше 90 дней")
        self.assertIn("Удалено завершённых записей: 1", controller.handle("подтверди очистку журнала"))
        self.assertEqual(store.count_scheduled_runs(), 0)

    def test_heartbeat_requires_matching_session(self):
        self.store.claim_scheduled_run(
            "checks", "daily:today", owner_session="auth-session",
            owner_pid=os.getpid(), owner_created=100.0,
        )
        self.assertFalse(self.store.heartbeat_scheduled_run("checks", "daily:today", "wrong"))
        self.assertTrue(self.store.heartbeat_scheduled_run("checks", "daily:today", "auth-session"))
        row = self.store.list_scheduled_runs()[0]
        self.assertFalse(row["needs_review"])
        self.assertEqual(row["owner_session"], "auth-session")
        self.store.finish_scheduled_run("checks", "daily:today", True)
        self.assertFalse(self.store.heartbeat_scheduled_run("checks", "daily:today", "auth-session"))

    def test_claim_health_is_conservative(self):
        row = {
            "status": "claimed", "needs_review": True,
            "owner_pid": None, "owner_created": None, "owner_session": "different",
        }
        self.assertEqual(describe_claim(row), "unknown")
        self.assertEqual(describe_claim({**row, "needs_review": False}), "recent_heartbeat")
        self.assertEqual(describe_claim({**row, "owner_session": "same"}, current_session="same"),
                         "own_runtime_stale")

    def test_process_identity_rejects_reused_pid(self):
        class FakeProc:
            def __init__(self, pid): pass
            def create_time(self): return 200.0
            def is_running(self): return True
            def status(self): return "running"
        fake = types.SimpleNamespace(Process=FakeProc, STATUS_ZOMBIE="zombie",
                                     NoSuchProcess=type("NoSuchProcess", (Exception,), {}),
                                     AccessDenied=type("AccessDenied", (Exception,), {}))
        with patch.dict("sys.modules", {"psutil": fake}):
            self.assertEqual(process_identity(pid=42, created=100.0), "owner_not_running")
            self.assertEqual(process_identity(pid=42, created=200.0), "owner_alive")

    def test_preexisting_journal_schema_is_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "CREATE TABLE scheduled_runs (workflow_id TEXT NOT NULL, "
                    "run_key TEXT NOT NULL, claimed REAL NOT NULL, status TEXT NOT NULL, "
                    "detail TEXT NOT NULL DEFAULT '', PRIMARY KEY (workflow_id, run_key))"
                )
                db.execute(
                    "INSERT INTO scheduled_runs VALUES ('legacy','key',10,'claimed','')"
                )
                db.commit()
            store = LocalStore(path)
            row = store.list_scheduled_runs()[0]
            self.assertEqual(row["owner_session"], "")
            self.assertTrue(row["needs_review"])

    def test_extracted_scheduler_records_success(self):
        store = self.store
        store.claim_scheduled_run("checks", "daily:run", owner_session="runtime")
        seen = []
        class Tools:
            def execute(self, name, args): seen.append(name); return "ok"
        class Runtime:
            stop_event = threading.Event()
            agent_controller = types.SimpleNamespace(
                store=store, tools=Tools(),
                workflows=types.SimpleNamespace(owner_session="runtime"),
            )
            def emit(self, kind, text): seen.append((kind, text))
        job = types.SimpleNamespace(
            flow_id="checks", label="test", run_key="daily:run",
            steps=[{"tool": "system_status", "args": {}}],
        )
        run_one_job(Runtime(), job)
        self.assertEqual(store.scheduled_run_status("checks", "daily:run"), "succeeded")
        self.assertIn("system_status", seen)

    def test_legacy_entrypoint_imports_extracted_modules(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "garfield_flagship.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        self.assertFalse(any(
            isinstance(node, ast.ClassDef) and node.name == "TTSQueue"
            for node in module.body
        ))
        self.assertIn("from garfield_runtime.tts_queue import TTSQueue", source)
        self.assertIn("from garfield_runtime.scheduler import schedule_loop", source)


if __name__ == "__main__":
    unittest.main()
