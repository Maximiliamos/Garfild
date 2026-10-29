"""Text and voice commands for planning, local notes, and workflow previews."""
from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Callable

from .runner import PlanRunner, WorkflowLibrary
from .storage import LocalStore
from .tools import ToolRegistry


class AgentController:
    def __init__(
        self,
        project_dir: Path,
        llm_getter: Callable[[], Any],
        stop_event: threading.Event | None = None,
        data_dir: Path | None = None,
        workspace: Path | None = None,
    ):
        default_data = (
            Path(os.environ["LOCALAPPDATA"]) / "Garfield"
            if os.environ.get("LOCALAPPDATA")
            else Path.home() / ".garfield"
        )
        self.store = LocalStore((data_dir or default_data) / "assistant.sqlite3")
        self.tools = ToolRegistry(workspace or (Path.home() / "Documents" / "GarfieldWorkspace"), self.store)
        self.runner = PlanRunner(self.tools, self.store, llm_getter, stop_event)
        self.workflows = WorkflowLibrary(Path(project_dir) / "garfield_workflows.json", self.runner)

    def handle(self, command: str) -> str | None:
        text = " ".join(command.strip().split())
        lower = text.lower()
        try:
            if lower.startswith(("агент ", "составь план ")):
                start = 6 if lower.startswith("агент ") else 13
                return self.runner.propose(text[start:])
            if lower in {"подтверди план", "выполни план"}:
                return self.runner.confirm()
            if lower in {"отмени план", "отмена плана"}:
                return self.runner.cancel()
            if lower in {"инструменты агента", "список инструментов агента"}:
                return "\n".join(f"{x['name']}: {x['description']} [{x['risk']}]" for x in self.tools.catalogue())
            if lower == "сценарии" or lower == "список сценариев":
                return self.workflows.names()
            if lower.startswith("запусти сценарий "):
                return self.workflows.preview(text[len("запусти сценарий "):].strip())
            if lower.startswith("запомни "):
                identifier = self.store.add_note(text[len("запомни "):])
                return f"Сохранено в локальных заметках: №{identifier}."
            if lower in {"мои заметки", "покажи заметки"}:
                notes = self.store.notes()
                return "\n".join(f"{note['id']}: {note['content']}" for note in notes) or "Заметок нет."
            if lower.startswith("найди заметку "):
                query = text[len("найди заметку "):].strip()
                notes = self.store.notes(query)
                return "\n".join(f"{note['id']}: {note['content']}" for note in notes) or "Ничего не найдено."
            if lower.startswith("забудь заметку "):
                identifier = text[len("забудь заметку "):].strip()
                if not re.fullmatch(r"\d+", identifier):
                    return "Укажите номер заметки, например «забудь заметку 3»."
                return "Заметка удалена." if self.store.delete_note(int(identifier)) else "Заметка не найдена."
            if lower.startswith("найди в истории "):
                query = text[len("найди в истории "):].strip()
                rows = self.store.search_messages(query)
                return "\n".join(f"{item['role']}: {item['text'][:400]}" for item in rows) or "Совпадений нет. Проверьте, включено ли сохранение истории."
        except Exception as error:
            logging.exception("Ошибка агента")
            return f"Ошибка агента: {error}"
        return None
