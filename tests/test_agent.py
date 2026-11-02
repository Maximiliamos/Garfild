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

    def test_workspace_creation_requires_new_files(self):
        self.tools.validate("write_file", {"path": "notes/todo.txt", "text": "one"})
        result = self.tools.execute("write_file", {"path": "notes/todo.txt", "text": "one"})
        self.assertIn("Новый файл", result)
        self.assertEqual((self.root / "workspace" / "notes" / "todo.txt").read_text(encoding="utf-8"), "one")
        with self.assertRaises(FileExistsError):
            self.tools.execute("write_file", {"path": "notes/todo.txt", "text": "two"})
        with self.assertRaises(ValueError):
            self.tools.validate("write_file", {"path": "run.exe", "text": "bad"})
        self.assertIn("Папка создана", self.tools.execute("create_folder", {"path": "data"}))

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

    def test_failed_plan_rolls_back_new_file_and_can_replan(self):
        fake = FakeLLM(json.dumps({"steps": [{"tool": "system_status", "args": {}}]}))
        runner = PlanRunner(self.tools, self.store, lambda: fake)
        preview = runner.preview("создать и проверить файл", [
            {"tool": "write_file", "args": {"path": "temporary.txt", "text": "data"}},
            {"tool": "read_file", "args": {"path": "missing.txt"}},
        ])
        self.assertIn("подтверди план", preview)
        result = runner.confirm()
        self.assertIn("error:", result)
        self.assertIn("rollback:", result)
        self.assertFalse((self.root / "workspace" / "temporary.txt").exists())
        self.assertIn("подтверди план", runner.propose_repair())
        self.assertIn("ok:", runner.confirm())
        self.assertIn("уже использована", runner.propose_repair())

    def test_file_created_event_runs_only_read_only(self):
        config = {"workflows": [
            {"id": "filewatch", "name": "Watch", "when_file_created": "incoming.txt",
             "steps": [{"tool": "system_status", "args": {}}]},
            {"id": "unsafe", "name": "Unsafe", "when_file_created": "incoming2.txt",
             "steps": [{"tool": "open_app", "args": {"name": "notepad"}}]},
        ]}
        (self.root / "garfield_workflows.json").write_text(json.dumps(config), encoding="utf-8")
        workflows = WorkflowLibrary(self.root / "garfield_workflows.json", self.runner)
        self.assertEqual(workflows.due_read_only(), [])
        (self.root / "workspace" / "incoming.txt").write_text("hi", encoding="utf-8")
        (self.root / "workspace" / "incoming2.txt").write_text("hi", encoding="utf-8")
        self.assertEqual(len(workflows.due_read_only()), 1)
        self.assertEqual(workflows.due_read_only(), [])

    def test_opt_in_sqlite_history_deletion_requires_confirmation(self):
        controller = AgentController(self.root, lambda: None, threading.Event(),
                                     self.root / "private-data", self.root / "workspace2")
        controller.store.add_message("user", "личная переписка")
        self.assertIn("Нет действительного", controller.handle("подтверди удаление истории"))
        self.assertEqual(len(controller.store.search_messages("личная")), 1)
        self.assertIn("Для продолжения", controller.handle("удали сохранённую историю"))
        self.assertIn("отменено", controller.handle("отмени удаление"))
        self.assertEqual(len(controller.store.search_messages("личная")), 1)
        controller.handle("удали сохраненную историю")
        self.assertIn("Удалено локальных записей: 1", controller.handle("подтверди удаление истории"))
        self.assertEqual(controller.store.search_messages("личная"), [])

    def test_all_notes_deletion_is_separate_and_confirmed(self):
        controller = AgentController(self.root, lambda: None, threading.Event(),
                                     self.root / "private-data2", self.root / "workspace3")
        controller.store.add_note("заметка секрет")
        controller.store.add_message("user", "разговор")
        self.assertIn("Нет действительного", controller.handle("подтверди удаление заметок"))
        controller.handle("удали все заметки")
        self.assertIn("Удалено локальных записей: 1", controller.handle("подтверди удаление заметок"))
        self.assertEqual(controller.store.notes(), [])
        self.assertEqual(len(controller.store.search_messages("разговор")), 1)

    def test_commands_recall_and_delete(self):
        controller = AgentController(self.root, lambda: None, threading.Event(), self.root / "db2", self.root / "workspace2")
        reply = controller.handle("запомни купить хлеб")
        self.assertIn("№", reply)
        self.assertIn("купить хлеб", controller.handle("мои заметки"))
        self.assertEqual(controller.handle("забудь заметку 1"), "Заметка удалена.")
        self.assertEqual(controller.handle("подтверди план"), "Нет ожидающего подтверждения плана.")


if __name__ == "__main__":
    unittest.main()
