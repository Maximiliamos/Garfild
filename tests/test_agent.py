"""Behavior tests of agent boundaries; no network, mic or OS access required."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

from garfield_agent.controller import AgentController
from garfield_agent.runner import PlanRunner, WorkflowLibrary
from garfield_agent.storage import LocalStore
from garfield_agent.tools import ToolRegistry


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def is_available(self):
        return True

    def ask(self, *args, **kwargs):
        self.calls += 1
        return self.response


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = LocalStore(self.root / "db" / "notes.sqlite3")
        self.tools = ToolRegistry(self.root / "workspace", self.store)
        self.runner = PlanRunner(self.tools, self.store, lambda: None)

    def test_memory_survives_reopen_and_deletes_by_id(self):
        identifier = self.store.add_note("купить бумагу")
        second = LocalStore(self.root / "db" / "notes.sqlite3")
        self.assertEqual(second.notes("бумагу")[0]["id"], identifier)
        self.assertTrue(second.delete_note(identifier))
        self.assertEqual(self.store.notes(), [])

    def test_history_search_and_escape(self):
        self.store.add_message("user", "Найти лот 123")
        self.store.add_message("assistant", "Результат")
        self.assertEqual(self.store.search_messages("лот")[0]["role"], "user")
        self.assertFalse(self.store.search_messages("%"))  # Percent is a literal, not a wildcard.

    def test_workspace_prevents_escape(self):
        outside = self.root / "private.txt"
        outside.write_text("secret", encoding="utf-8")
        with self.assertRaises(PermissionError):
            self.tools.execute("read_file", {"path": "../private.txt"})
        with self.assertRaises(PermissionError):
            self.tools.execute("read_file", {"path": str(outside)})
        self.assertRaises(ValueError, self.tools.execute, "open_app", {"name": "powershell"})

    def test_public_browsing_only(self):
        for address in ("file:///etc/passwd", "http://127.0.0.1:8080", "https://localhost/a", "https://10.1.1.1/a"):
            with self.assertRaises(ValueError):
                self.tools.validate("browser_read", {"url": address})
        self.tools.validate("browser_read", {"url": "https://example.org"})

    def test_requires_approval_before_any_execution(self):
        path = self.root / "workspace" / "sample.txt"
        path.write_text("abc", encoding="utf-8")
        text = self.runner.preview("read", [{"tool": "read_file", "args": {"path": "sample.txt"}}])
        self.assertIn("подтверди план", text)
        self.assertIsNotNone(self.runner.pending)
        # The runner does not execute during preview.
        self.assertEqual(self.runner.confirm().splitlines()[-1], "1. ok: abc")
        self.assertIn("Нет ожидающего", self.runner.confirm())

    def test_invalid_agent_plan_is_rejected(self):
        for steps in (
            [{"tool": "shell", "args": {"code": "whoami"}}],
            [{"tool": "open_app", "args": {"name": "powershell"}}],
            [{"tool": "read_file", "args": {"path": "../secrets.txt"}}],
            [{"tool": "system_status", "args": {}}] * 7,
        ):
            with self.assertRaises((ValueError, PermissionError)):
                self.runner.preview("unsafe", steps)
        self.assertIsNone(self.runner.pending)

    def test_model_proposal_not_executed_automatically(self):
        fake = FakeLLM(json.dumps({"steps": [{"tool": "remember_note", "args": {"text": "test item"}}]}))
        runner = PlanRunner(self.tools, self.store, lambda: fake)
        preview = runner.propose("запомни мой тестовый пункт")
        self.assertIn("подтверди план", preview)
        self.assertEqual(self.store.notes(), [])
        self.assertIn("ok:", runner.confirm())
        self.assertEqual(self.store.notes()[0]["content"], "test item")

    def test_predefined_workflows_and_safe_daily_trigger(self):
        raw = {"workflows": [
            {"id": "hello", "name": "Test", "steps": [{"tool": "system_status", "args": {}}], "daily_at": "09:00"},
            {"id": "unsafe", "name": "Unsafe", "steps": [{"tool": "open_app", "args": {"name": "notepad"}}], "daily_at": "09:00"},
        ]}
        (self.root / "garfield_workflows.json").write_text(json.dumps(raw), encoding="utf-8")
        workflows = WorkflowLibrary(self.root / "garfield_workflows.json", self.runner)
        self.assertEqual(len(workflows.due_read_only(datetime(2026, 10, 29, 9, 0))), 1)
        self.assertEqual(len(workflows.due_read_only(datetime(2026, 10, 29, 9, 0))), 0)
        self.assertIn("подтверди план", workflows.preview("hello"))

    def test_commands_recall_and_delete(self):
        controller = AgentController(self.root, lambda: None, threading.Event(), self.root / "db2", self.root / "workspace2")
        reply = controller.handle("запомни купить хлеб")
        self.assertIn("№", reply)
        self.assertIn("купить хлеб", controller.handle("мои заметки"))
        self.assertEqual(controller.handle("забудь заметку 1"), "Заметка удалена.")
        self.assertEqual(controller.handle("подтверди план"), "Нет ожидающего подтверждения плана.")


if __name__ == "__main__":
    unittest.main()
