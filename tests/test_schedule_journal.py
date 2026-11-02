"""Scheduled-run journal and manual-only retry regression tests."""
from __future__ import annotations

import json
from contextlib import closing
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

from garfield_agent.controller import AgentController
from garfield_agent.runner import PlanRunner, WorkflowLibrary
from garfield_agent.storage import LocalStore
from garfield_agent.tools import ToolRegistry


class ScheduleJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = LocalStore(self.root / "history.sqlite3")
        self.tools = ToolRegistry(self.root / "workspace", self.store)
        self.runner = PlanRunner(self.tools, self.store, lambda: None)
        self.file = self.root / "garfield_workflows.json"

    def configure(self):
        self.file.write_text(json.dumps({"workflows": [
            {"id": "daily", "name": "Daily", "daily_at": "09:00",
             "steps": [{"tool": "system_status", "args": {}}]},
            {"id": "file-watch", "name": "Files", "when_file_created": "trigger.txt",
             "steps": [{"tool": "system_status", "args": {}}]},
        ]}), encoding="utf-8")
        return WorkflowLibrary(self.file, self.runner)

    def test_scheduled_journal_success_and_failure(self):
        workflow = self.configure()
        job = workflow.due_read_only(datetime(2026, 11, 2, 9, 0))[0]
        self.assertEqual(self.store.scheduled_run_status("daily", job.run_key), "claimed")
        self.store.finish_scheduled_run("daily", job.run_key, False, "Test failure")
        record = self.store.latest_scheduled_run("daily")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["detail"], "Test failure")
        self.assertEqual(len(self.store.list_scheduled_runs()), 1)
        with self.assertRaises(ValueError):
            self.store.finish_scheduled_run("daily", job.run_key, True)
        self.assertEqual(self.store.scheduled_run_status("daily", job.run_key), "failed")

    def test_manual_retry_only_previews_failed_run(self):
        flow = self.configure()
        with self.assertRaises(ValueError):
            flow.retry_failed_preview("daily")
        job = flow.due_read_only(datetime(2026, 11, 2, 9, 0))[0]
        self.store.finish_scheduled_run("daily", job.run_key, False, "Network unavailable")
        preview = flow.retry_failed_preview("daily")
        self.assertIn("подтверди план", preview)
        self.assertIn("ТЕКУЩАЯ версия", preview)
        self.assertEqual(self.store.scheduled_run_status("daily", job.run_key), "failed")
        self.assertIn("1. ok:", self.runner.confirm())
        # Manual success does not change or clear the original failed background claim.
        self.assertEqual(self.store.scheduled_run_status("daily", job.run_key), "failed")
        self.assertEqual(flow.due_read_only(datetime(2026, 11, 2, 9, 0)), [])

    def test_file_trigger_has_journal_entry(self):
        flow = self.configure()
        self.assertEqual(flow.due_read_only(datetime(2026, 11, 2, 10, 0)), [])
        (self.root / "workspace" / "trigger.txt").write_text("start", encoding="utf-8")
        jobs = flow.due_read_only(datetime(2026, 11, 2, 10, 1))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].flow_id, "file-watch")
        self.assertTrue(jobs[0].run_key.startswith("file:"))
        self.assertEqual(self.store.scheduled_run_status("file-watch", jobs[0].run_key), "claimed")
        self.store.finish_scheduled_run("file-watch", jobs[0].run_key, True, "1 step")
        self.assertEqual(self.store.latest_scheduled_run("file-watch")["status"], "succeeded")

    def test_failed_retry_rejects_removed_workflow(self):
        flow = self.configure()
        job = flow.due_read_only(datetime(2026, 11, 2, 9, 0))[0]
        self.store.finish_scheduled_run("daily", job.run_key, False, "failed")
        self.file.write_text('{"workflows":[]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            flow.retry_failed_preview("daily")

    def test_command_exposes_journal_and_requires_approval(self):
        controller = AgentController(
            self.root, lambda: None, threading.Event(),
            self.root / "controller-data", self.root / "workspace-control"
        )
        self.file.write_text(json.dumps({"workflows": [
            {"id": "daily", "daily_at": "09:00", "steps": [
                {"tool": "system_status", "args": {}}
            ]}
        ]}), encoding="utf-8")
        self.assertIn("запусков", (controller.handle("журнал заданий") or "").lower())
        flow = controller.workflows
        job = flow.due_read_only(datetime(2026, 11, 2, 9, 0))[0]
        controller.store.finish_scheduled_run("daily", job.run_key, False, "failed")
        self.assertIn("failed", controller.handle("журнал заданий"))
        self.assertIn("подтверди план", controller.handle("повтори неудачный сценарий daily"))
        self.assertEqual(controller.store.scheduled_run_status("daily", job.run_key), "failed")
        controller.handle("отмени план")

    def test_existing_database_migrates_detail_column(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.sqlite3"
            # sqlite3.Connection context manager commits but does not close.
            # Windows refuses to delete temporary DB files with open handles.
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE scheduled_runs (workflow_id TEXT NOT NULL, run_key TEXT NOT NULL, claimed REAL NOT NULL, status TEXT NOT NULL, PRIMARY KEY (workflow_id, run_key))")
                db.execute("INSERT INTO scheduled_runs(workflow_id, run_key, claimed, status) VALUES ('old', 'daily:2026-11-02:09:00', 1, 'claimed')")
                db.commit()
            migrated = LocalStore(path)
            migrated.finish_scheduled_run("old", "daily:2026-11-02:09:00", False, "err")
            self.assertEqual(migrated.latest_scheduled_run("old")["detail"], "err")


if __name__ == "__main__":
    unittest.main()
