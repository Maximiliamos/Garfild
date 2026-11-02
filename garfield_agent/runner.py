"""Preview-first agent planning and declarative workflows.

No dynamically generated Python, shell commands or unreviewed autonomous actions.
The model may propose a strictly validated plan; execution requires explicit consent.
"""
from __future__ import annotations

import json
import hashlib
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


@dataclass(frozen=True)
class ScheduledJob:
    flow_id: str
    label: str
    steps: list[dict]
    run_key: str | None = None


class PlanRunner:
    def __init__(self, tools: ToolRegistry, store: LocalStore, llm_getter: Callable[[], Any], stop_event: threading.Event | None = None):
        self.tools = tools
        self.store = store
        self.llm_getter = llm_getter
        self.stop_event = stop_event or threading.Event()
        self.pending: PendingPlan | None = None
        self.last_failure: dict[str, str] | None = None
        self._repair_used = False
        self._state_lock = threading.RLock()
        self._executing = False

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
        with self._state_lock:
            if self._executing:
                raise RuntimeError("Нельзя заменить план, пока выполняется предыдущий.")
            self.pending = PendingPlan(label, clean, time.monotonic())
        lines = [f"План «{label}» ({len(clean)} шагов):"]
        for index, item in enumerate(clean, 1):
            spec = self.tools.SPECS[item["tool"]]
            details = ", ".join(f"{k}={str(v)[:65]}" for k, v in item["args"].items())
            lines.append(f"{index}. {spec.description} [{spec.risk}] {details}")
        lines.append("Для исполнения в течение 120 секунд введите «подтверди план». Иначе «отмени план».")
        return "\n".join(lines)

    def propose(self, task: str) -> str:
        with self._state_lock:
            if self._executing:
                raise RuntimeError("Дождитесь завершения выполняемого плана.")
            self.last_failure = None
            self._repair_used = False
        return self._create_plan(task)

    def propose_repair(self) -> str:
        with self._state_lock:
            if self._executing:
                return "Нельзя перепланировать во время выполнения."
            failure = self.last_failure
            if not failure or self._repair_used:
                return "Нет ошибки для перепланирования или попытка уже использована."
            self._repair_used = True
        # Only the failed step and future steps may be proposed again;
        # completed steps are never retried as part of this repair.
        task = (
            f"Изначальная задача: {failure['label']}. "
            f"Ошибка на шаге: {failure['tool']}, сообщение: {failure['error']}. "
            "Предложи альтернативные действия только для невыполненного остатка. "
            "Уже завершённые шаги повторять нельзя."
        )
        try:
            return self._create_plan(task)
        except Exception:
            with self._state_lock:
                self._repair_used = False
            raise

    def _create_plan(self, task: str) -> str:
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

    @staticmethod
    def _rollback_file(path: Path, fingerprint: str) -> str:
        # Never delete anything that has been changed or replaced since we made it.
        if not path.is_file() or path.is_symlink():
            return "Пропущено: файл уже отсутствует или заменён"
        if hashlib.sha256(path.read_bytes()).hexdigest() != fingerprint:
            return "Пропущено: файл изменился"
        path.unlink()
        return "Новый файл удалён"

    def confirm(self) -> str:
        with self._state_lock:
            if self._executing:
                return "План уже выполняется; повторное подтверждение отклонено."
            pending = self.pending
            self.pending = None
            if pending is None:
                return "Нет ожидающего подтверждения плана."
            if time.monotonic() - pending.created > 120:
                return "План устарел и отменён. Создайте его заново."
            self._executing = True
        try:
            return self._execute_claimed_plan(pending)
        finally:
            with self._state_lock:
                self._executing = False

    def _execute_claimed_plan(self, pending: PendingPlan) -> str:
        steps = self.validate_steps(pending.steps)
        result = []
        undo: list[tuple[str, Path, str]] = []
        self.last_failure = None
        for index, item in enumerate(steps, 1):
            if self.stop_event.is_set():
                result.append({"step": index, "status": "cancelled"})
                break
            try:
                name, args = item["tool"], item["args"]
                created_path = None
                if name in {"write_file", "create_folder"}:
                    target = self.tools._within_workspace(args["path"])
                    if not target.exists():
                        created_path = target
                message = self.tools.execute(name, args)
                if created_path is not None and created_path.exists():
                    if name == "write_file":
                        undo.append(("file", created_path, hashlib.sha256(created_path.read_bytes()).hexdigest()))
                    elif name == "create_folder":
                        undo.append(("directory", created_path, ""))
                result.append({"step": index, "status": "ok", "message": str(message)[:1000]})
            except Exception as error:
                logging.exception("Ошибка шага %s", index)
                result.append({"step": index, "status": "error", "message": str(error)[:300]})
                self.last_failure = {"label": pending.label, "tool": item["tool"], "error": str(error)[:200]}
                for kind, path, fingerprint in reversed(undo):
                    try:
                        if kind == "file":
                            detail = self._rollback_file(path, fingerprint)
                        else:
                            path.rmdir()  # Only if still empty; never recursive
                            detail = "Созданная пустая папка удалена"
                    except OSError as rollback_error:
                        detail = f"Откат пропущен: {rollback_error}"
                    result.append({"step": index, "status": "rollback", "message": detail[:220]})
                break
        self.store.record_run(steps, result)
        lines = [f"План «{pending.label}»:"]
        lines.extend(f"{row['step']}. {row['status']}: {row.get('message', '')}" for row in result)
        return "\n".join(lines)

    def cancel(self) -> str:
        with self._state_lock:
            self.pending = None
            if self._executing:
                return "Ожидающий план отменён. Уже выполняющееся действие не прерывается."
        return "План отменён."


class WorkflowLibrary:
    """Read predefined JSON workflows, never silently execute dangerous steps."""

    def __init__(self, path: Path, runner: PlanRunner):
        self.path = Path(path)
        self.runner = runner
        self._observed_files: dict[str, bool] = {}

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
            watched = flow.get("when_file_created")
            if watched is not None:
                if not isinstance(watched, str) or not watched.strip():
                    raise ValueError("when_file_created должен указывать путь к файлу")
                self.runner.tools._within_workspace(watched)
                if schedule:
                    raise ValueError("Выберите одно условие запуска: время или новый файл")
            result.append({"id": identifier, "name": str(flow.get("name", identifier))[:80], "steps": steps, "daily_at": schedule, "when_file_created": watched})
        return result

    def names(self) -> str:
        flows = self.all()
        return "\n".join(f"{flow['id']}: {flow['name']}" + (f" (ежедневно {flow['daily_at']})" if flow["daily_at"] else "") for flow in flows) or "Нет сценариев. Создайте garfield_workflows.json."

    def preview(self, identifier: str) -> str:
        for flow in self.all():
            if flow["id"] == identifier:
                return self.runner.preview(flow["name"], flow["steps"])
        raise ValueError("Сценарий не найден: " + identifier)

    def retry_failed_preview(self, identifier: str) -> str:
        """Manual, confirmed replay of the current workflow definition.

        Does not reset the original scheduled run or automatically execute.
        """
        latest = self.runner.store.latest_scheduled_run(identifier)
        if latest is None or latest["status"] != "failed":
            raise ValueError("Нет последнего неуспешного фонового запуска для этого сценария")
        flow = next((item for item in self.all() if item["id"] == identifier), None)
        if flow is None:
            raise ValueError("Сценарий удалён или отсутствует в конфигурации")
        return (
            "Ручной повтор сценария после ошибки. "
            "Будет использована ТЕКУЩАЯ версия шагов, а не историческая.\n"
            + self.runner.preview(flow["name"], flow["steps"])
        )

    def due_read_only(self, now: datetime | None = None) -> list[ScheduledJob]:
        """Claim allowed daily jobs in SQLite before returning them.

        Daily jobs run at most once per date even after restarting Garfield.
        Claims made before a crash are NOT retried automatically. File creation
        events still use in-memory edge detection and are not durable.
        """
        now = now or datetime.now()
        date_key = now.strftime("%Y-%m-%d")
        clock = now.strftime("%H:%M")
        jobs: list[ScheduledJob] = []
        for flow in self.all():
            if not all(step["tool"] in self.runner.tools.UNATTENDED_SAFE
                       for step in flow["steps"]):
                continue
            run_key: str | None = None
            if flow["daily_at"] == clock:
                candidate = f"daily:{date_key}:{clock}"
                if self.runner.store.claim_scheduled_run(flow["id"], candidate):
                    run_key = candidate
                    jobs.append(ScheduledJob(flow["id"], flow["name"], flow["steps"], run_key))
            watched = flow["when_file_created"]
            if watched:
                path = self.runner.tools._within_workspace(watched)
                exists = path.is_file()
                previous = self._observed_files.get(flow["id"])
                self._observed_files[flow["id"]] = exists
                if previous is False and exists:
                    event_key = self.runner.store.claim_file_event_run(flow["id"])
                    jobs.append(ScheduledJob(flow["id"], flow["name"], flow["steps"], event_key))
        return jobs
