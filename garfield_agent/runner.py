"""Preview-first agent planning and declarative workflows.

No dynamically generated Python, shell commands or unreviewed autonomous actions.
The model may propose a strictly validated plan; execution requires explicit consent.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .storage import LocalStore
from .tools import ToolRegistry


MAX_STEPS = 6


@dataclass
class PendingPlan:
    label: str
    steps: list[dict]
    created: float


class PlanRunner:
    def __init__(self, tools: ToolRegistry, store: LocalStore, llm_getter: Callable[[], Any], stop_event: threading.Event | None = None):
        self.tools = tools
        self.store = store
        self.llm_getter = llm_getter
        self.stop_event = stop_event or threading.Event()
        self.pending: PendingPlan | None = None

    def validate_steps(self, steps: Any) -> list[dict]:
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
            raise ValueError(f"План должен содержать от 1 до {MAX_STEPS} действий")
        cleaned = []
        for item in steps:
            if not isinstance(item, dict) or set(item) != {"tool", "args"}:
                raise ValueError("Шаг должен иметь только поля tool и args")
            name, args = item["tool"], item["args"]
            if not isinstance(name, str):
                raise ValueError("Неверное имя инструмента")
            self.tools.validate(name, args)
            cleaned.append({"tool": name, "args": args.copy()})
        return cleaned

    def preview(self, label: str, steps: list[dict]) -> str:
        clean = self.validate_steps(steps)
        self.pending = PendingPlan(label, clean, time.monotonic())
        lines = [f"План «{label}» ({len(clean)} шагов):"]
        for index, item in enumerate(clean, 1):
            spec = self.tools.SPECS[item["tool"]]
            details = ", ".join(f"{k}={str(v)[:65]}" for k, v in item["args"].items())
            lines.append(f"{index}. {spec.description} [{spec.risk}] {details}")
        lines.append("Для исполнения в течение 120 секунд введите «подтверди план». Иначе «отмени план».")
        return "\n".join(lines)

    def propose(self, task: str) -> str:
        task = task.strip()
        if not 4 <= len(task) <= 800:
            raise ValueError("Опишите задачу длиной от 4 до 800 символов")
        llm = self.llm_getter()
        if llm is None or not llm.is_available():
            raise RuntimeError("Выберите и настройте ИИ-провайдер для планирования")
        schema = json.dumps(self.tools.catalogue(), ensure_ascii=False)
        prompt = (
            "Ты планировщик действий на компьютере. Верни только JSON-объект вида "
            '{"steps":[{"tool":"system_status","args":{}}]}. '
            "Используй ТОЛЬКО перечисленные инструменты и их аргументы. "
            "Не пытайся выполнить задачу самостоятельно, не используй shell, code или Python. "
            f"Не более {MAX_STEPS} шагов. Когда задача не поддерживается, верни JSON с полем error. "
            "Инструменты: " + schema + "\nЗадача: " + task
        )
        # A standalone empty history avoids importing the desktop/audio core here.
        class EmptyHistory:
            def as_messages(self) -> list[dict[str, str]]:
                return []
        response = llm.ask(prompt, "Гарфилд", EmptyHistory(), max_tokens=800, timeout_sec=25)
        response = response.strip()
        if response.startswith("```"):
            response = re.sub(r"^\x60{3}(?:json)?\s*|\s*\x60{3}$", "", response).strip()
        try:
            data = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ValueError("Модель не вернула JSON-план. Попробуйте уточнить задачу") from exc
        if not isinstance(data, dict) or data.get("error"):
            raise ValueError(str(data.get("error", "Модель не составила план"))[:300] if isinstance(data, dict) else "Неверный план")
        return self.preview(task, data.get("steps"))

    def confirm(self) -> str:
        pending = self.pending
        self.pending = None
        if pending is None:
            return "Нет ожидающего подтверждения плана."
        if time.monotonic() - pending.created > 120:
            return "План устарел и отменён. Создайте его заново."
        steps = self.validate_steps(pending.steps)  # validate again at execution
        result = []
        for index, item in enumerate(steps, 1):
            if self.stop_event.is_set():
                result.append({"step": index, "status": "cancelled"})
                break
            try:
                message = self.tools.execute(item["tool"], item["args"])
                result.append({"step": index, "status": "ok", "message": str(message)[:1000]})
            except Exception as error:
                logging.exception("Ошибка шага %s", index)
                result.append({"step": index, "status": "error", "message": str(error)[:300]})
                break
        self.store.record_run(steps, result)
        lines = [f"План «{pending.label}»:"]
        lines.extend(f"{row['step']}. {row['status']}: {row.get('message', '')}" for row in result)
        return "\n".join(lines)

    def cancel(self) -> str:
        self.pending = None
        return "План отменён."


class WorkflowLibrary:
    """Read predefined JSON workflows, never silently execute dangerous steps."""

    def __init__(self, path: Path, runner: PlanRunner):
        self.path = Path(path)
        self.runner = runner
        self._last_run_date: dict[str, str] = {}

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        obj = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict) or not isinstance(obj.get("workflows"), list):
            raise ValueError("Файл сценариев должен содержать список workflows")
        result = []
        ids = set()
        for flow in obj["workflows"]:
            if not isinstance(flow, dict) or not isinstance(flow.get("id"), str):
                raise ValueError("Сценарий должен иметь строковый id")
            identifier = flow["id"].strip()
            if not re.fullmatch(r"[a-z0-9_-]{1,40}", identifier) or identifier in ids:
                raise ValueError("Некорректный или повторяющийся id сценария")
            ids.add(identifier)
            steps = self.runner.validate_steps(flow.get("steps"))
            schedule = flow.get("daily_at")
            if schedule is not None and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(schedule)):
                raise ValueError("daily_at должен быть в формате HH:MM")
            result.append({"id": identifier, "name": str(flow.get("name", identifier))[:80], "steps": steps, "daily_at": schedule})
        return result

    def names(self) -> str:
        flows = self.all()
        return "\n".join(f"{flow['id']}: {flow['name']}" + (f" (ежедневно {flow['daily_at']})" if flow["daily_at"] else "") for flow in flows) or "Нет сценариев. Создайте garfield_workflows.json."

    def preview(self, identifier: str) -> str:
        for flow in self.all():
            if flow["id"] == identifier:
                return self.runner.preview(flow["name"], flow["steps"])
        raise ValueError("Сценарий не найден: " + identifier)

    def due_read_only(self, now: datetime | None = None) -> list[tuple[str, list[dict]]]:
        """Scheduled jobs can run ONLY read-only tools; others require manual confirmation."""
        now = now or datetime.now()
        date_key = now.strftime("%Y-%m-%d")
        clock = now.strftime("%H:%M")
        jobs = []
        for flow in self.all():
            if flow["daily_at"] != clock or self._last_run_date.get(flow["id"]) == date_key:
                continue
            self._last_run_date[flow["id"]] = date_key
            if all(self.runner.tools.SPECS[step["tool"]].risk == "read" for step in flow["steps"]):
                jobs.append((flow["name"], flow["steps"]))
        return jobs
