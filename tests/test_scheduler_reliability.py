"""Durable scheduled-run claims and one-shot plan confirmation regressions."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

from garfield_agent.runner import PlanRunner, WorkflowLibrary
from garfield_agent.storage import LocalStore
from garfield_agent.tools import ToolRegistry


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / "db.sqlite3"
        self.store = LocalStore(self.db_path)
        self.tools = ToolRegistry(self.root / "workspace", self.store)
        self.runner = PlanRunner(self.tools, self.store, lambda: None)
        self.flows_path = self.root / "garfield_workflows.json"

    def configure(self, flows):
        self.flows_path.write_text(
            json.dumps({"workflows": flows}, ensure_ascii=False), encoding="utf-8"
        )

    def test_daily_schedule_claim_survives_restart(self):
        self.configure([
            {"id": "morning", "name": "Morning", "daily_at": "09:00",
             "steps": [{"tool": "system_status", "args": {}}]},
        ])
        moment = datetime(2026, 11, 2, 9, 0)
        flow = WorkflowLibrary(self.flows_path, self.runner)
        jobs = flow.due_read_only(moment)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].run_key, "daily:2026-11-02:09:00")
        self.assertEqual(self.store.scheduled_run_status("morning", jobs[0].run_key), "claimed")
        # Simulate application restart with a new store and workflow object.
        reopened_store = LocalStore(self.db_path)
        new_runner = PlanRunner(self.tools, reopened_store, lambda: None)
        fresh = WorkflowLibrary(self.flows_path, new_runner)
        self.assertEqual(fresh.due_read_only(moment), [])
        reopened_store.finish_scheduled_run("morning", jobs[0].run_key, True)
        self.assertEqual(self.store.scheduled_run_status("morning", jobs[0].run_key), "succeeded")
        self.assertEqual(fresh.due_read_only(moment), [])
        self.assertEqual(len(fresh.due_read_only(datetime(2026, 11, 3, 9, 0))), 1)

    def test_unattended_workflows_are_strictly_allowlisted(self):
        self.configure([
            {"id": "notes", "name": "Private notes", "daily_at": "09:00",
             "steps": [{"tool": "recall_notes", "args": {}}]},
            {"id": "files", "name": "Files", "daily_at": "09:00",
             "steps": [{"tool": "list_files", "args": {}}]},
            {"id": "mixed", "name": "Mixed", "daily_at": "09:00",
             "steps": [
                 {"tool": "system_status", "args": {}},
                 {"tool": "read_file", "args": {"path": "secret.txt"}}
             ]},
            {"id": "safe", "name": "Safe", "daily_at": "09:00",
             "steps": [{"tool": "system_status", "args": {}}]},
        ])
        jobs = WorkflowLibrary(self.flows_path, self.runner).due_read_only(
            datetime(2026, 11, 2, 9, 0)
        )
        self.assertEqual([job.flow_id for job in jobs], ["safe"])
        self.assertIsNone(self.store.scheduled_run_status("notes", "daily:2026-11-02:09:00"))
        self.assertIsNone(self.store.scheduled_run_status("files", "daily:2026-11-02:09:00"))
        self.assertIsNone(self.store.scheduled_run_status("mixed", "daily:2026-11-02:09:00"))

    def test_failed_claim_is_not_reexecuted_unattended(self):
        self.configure([
            {"id": "check", "steps": [{"tool": "system_status", "args": {}}],
             "daily_at": "09:00"},
        ])
        moment = datetime(2026, 11, 2, 9, 0)
        job = WorkflowLibrary(self.flows_path, self.runner).due_read_only(moment)[0]
        self.store.finish_scheduled_run(job.flow_id, job.run_key, False)
        self.assertEqual(self.store.scheduled_run_status(job.flow_id, job.run_key), "failed")
        self.assertEqual(WorkflowLibrary(self.flows_path, self.runner).due_read_only(moment), [])

    def test_file_trigger_does_not_expose_private_automatic_reads(self):
        self.configure([
            {"id": "private", "when_file_created": "signal.txt",
             "steps": [{"tool": "recall_notes", "args": {}}]},
            {"id": "public", "when_file_created": "signal.txt",
             "steps": [{"tool": "system_status", "args": {}}]},
        ])
        flows = WorkflowLibrary(self.flows_path, self.runner)
        self.assertEqual(flows.due_read_only(), [])
        (self.root / "workspace" / "signal.txt").write_text("signal", encoding="utf-8")
        self.assertEqual([job.flow_id for job in flows.due_read_only()], ["public"])

    def test_simultaneous_confirmations_execute_once(self):
        entered = threading.Event()
        release = threading.Event()
        count = []
        original = self.tools.execute

        def blocking(tool, args):
            entered.set()
            self.assertTrue(release.wait(5), "Timed out waiting for test release")
            count.append(tool)
            return "OK"

        self.tools.execute = blocking
        self.addCleanup(lambda: setattr(self.tools, "execute", original))
        self.runner.preview("check", [{"tool": "system_status", "args": {}}])
        responses = []
        worker = threading.Thread(target=lambda: responses.append(self.runner.confirm()), daemon=True)
        worker.start()
        self.assertTrue(entered.wait(5), "First confirmation never entered tool")
        second = self.runner.confirm()
        self.assertIn("уже выполняется", second)
        release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(count, ["system_status"])
        self.assertEqual(len(responses), 1)
        self.assertIn("1. ok:", responses[0])
        self.assertIn("Нет ожидающего", self.runner.confirm())


if __name__ == "__main__":
    unittest.main()
