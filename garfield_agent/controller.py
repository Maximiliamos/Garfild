"""Text and voice commands for planning, local notes, and workflow previews."""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .runner import PlanRunner, WorkflowLibrary
from .storage import LocalStore
from .tools import ToolRegistry
from .vision import analyze_screen
from .updates import UpdateManager
from .model_manager import ModelManager


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
        self.tools = ToolRegistry(workspace or (Path.home() / "Documents" / "GarfieldWorkspace"), self.store, Path(project_dir) / "garfield_mcp_servers.json")
        self.runner = PlanRunner(self.tools, self.store, llm_getter, stop_event)
        self.updater = UpdateManager(project_dir)
        self.models = ModelManager()
        self.workflows = WorkflowLibrary(Path(project_dir) / "garfield_workflows.json", self.runner)
        self._pending_clear: tuple[str, float] | None = None
        self._privacy_lock = threading.Lock()

    def handle(self, command: str) -> str | None:
        text = " ".join(command.strip().split())
        lower = text.lower()
        try:
            if lower in {"удали сохраненную историю", "удали сохранённую историю"}:
                with self._privacy_lock:
                    self._pending_clear = ("history", time.monotonic())
                return "Будут удалены все сохранённые диалоги из SQLite. Для продолжения в течение 120 секунд введите «подтверди удаление истории». Для отказа — «отмени удаление»."
            if lower == "удали все заметки":
                with self._privacy_lock:
                    self._pending_clear = ("notes", time.monotonic())
                return "Будут удалены все личные заметки из SQLite. Для продолжения в течение 120 секунд введите «подтверди удаление заметок». Для отказа — «отмени удаление»."
            if lower == "отмени удаление":
                with self._privacy_lock:
                    self._pending_clear = None
                return "Удаление отменено."
            if lower in {"подтверди удаление истории", "подтверди удаление заметок"}:
                choice = "history" if lower.endswith("истории") else "notes"
                with self._privacy_lock:
                    pending = self._pending_clear
                    self._pending_clear = None
                    authorized = bool(pending and pending[0] == choice and time.monotonic() - pending[1] <= 120)
                    if not authorized:
                        return "Нет действительного запроса на удаление. Повторите команду подготовки."
                    count = (self.store.clear_saved_history() if choice == "history"
                             else self.store.clear_all_notes())
                return f"Удалено локальных записей: {count}. Старые экспортированные файлы и резервные копии не затронуты."
            if lower in {"посмотри на экран", "что на экране", "опиши экран"} or lower.startswith("посмотри на экран и "):
                task = text[len("посмотри на экран и "):] if lower.startswith("посмотри на экран и ") else "Опиши, что видно на экране по-русски."
                return analyze_screen(task, model=os.getenv("GARFIELD_VISION_MODEL", "llava:7b"))
            if lower.startswith(("агент ", "составь план ")):
                start = 6 if lower.startswith("агент ") else 13
                return self.runner.propose(text[start:])
            if lower in {"исправь план", "предложи исправление", "перепланируй"}:
                return self.runner.propose_repair()
            if lower in {"подтверди план", "выполни план"}:
                return self.runner.confirm()
            if lower in {"отмени план", "отмена плана"}:
                return self.runner.cancel()
            if lower.startswith("скачай модель "):
                return self.models.prepare(lower[len("скачай модель "):].strip())
            if lower == "подтверди загрузку модели":
                return self.models.confirm()
            if lower == "отмени загрузку модели":
                return self.models.cancel()
            if lower in {"проверь обновления", "проверить обновления", "есть обновление"}:
                return self.updater.check()
            if lower in {"подтверди обновление", "установи обновление"}:
                return self.updater.apply()
            if lower == "отмени обновление":
                return self.updater.cancel()
            if lower == "mcp серверы":
                servers = self.tools.mcp.servers()
                return "\n".join(f"{key}: {', '.join(sorted(value['allowed_tools']))}" for key, value in servers.items()) or "MCP-серверы не настроены"
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
