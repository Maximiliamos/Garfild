"""Agent and workflow controls with explicit confirmation and JSON validation."""
from __future__ import annotations

import json
import os
import tempfile
import tkinter as tk
from datetime import datetime
from pathlib import Path

import customtkinter as ctk

from garfield_agent.runner import WorkflowLibrary
from garfield_runtime.schedule_health import describe_claim
from ..components import action_button, card
from ..theme import COLORS, FONTS
from ..workflow_builder import WorkflowBuilder


class AutomationPage(ctk.CTkFrame):
    def __init__(self, parent, adapter, app):
        super().__init__(parent, fg_color="transparent")
        self.adapter = adapter
        self.app = app
        self.agent = adapter.runtime.agent_controller
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        tabs = ctk.CTkTabview(self, fg_color=COLORS["surface"])
        tabs.grid(row=0, column=0, sticky="nsew")
        self.tabs = tabs
        for name in ("ИИ-агент", "Сценарии", "Память", "Журнал"):
            tabs.add(name)
            tabs.tab(name).grid_columnconfigure(0, weight=1)

        agent_tab = tabs.tab("ИИ-агент")
        ctk.CTkLabel(
            agent_tab, text="Опишите задачу. Перед любым действием будет показан план.",
            text_color=COLORS["text_secondary"], font=FONTS["body"], anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        self.task = ctk.CTkTextbox(agent_tab, height=110, font=FONTS["body"], fg_color=COLORS["input"])
        self.task.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
        controls = ctk.CTkFrame(agent_tab, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="w", padx=16)
        action_button(controls, "Составить план", self.propose, width=160).grid(row=0, column=0, padx=(0, 8))
        action_button(controls, "Подтвердить", self.confirm, width=130, tone="ghost").grid(row=0, column=1, padx=(0, 8))
        action_button(controls, "Отменить", self.cancel, width=120, tone="danger").grid(row=0, column=2)
        self.agent_output = ctk.CTkTextbox(agent_tab, font=FONTS["mono"], fg_color=COLORS["input"], wrap="word")
        self.agent_output.grid(row=3, column=0, sticky="nsew", padx=16, pady=12)
        agent_tab.grid_rowconfigure(3, weight=1)

        flow_tab = tabs.tab("Сценарии")
        ctk.CTkLabel(flow_tab, text="Сценарии запускаются вручную. Сохранение проверяет все инструменты и параметры.",
                     font=FONTS["body"], text_color=COLORS["text_secondary"], anchor="w").grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        self.flow_json = ctk.CTkTextbox(flow_tab, font=FONTS["mono"], fg_color=COLORS["input"])
        self.flow_json.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))
        flow_tab.grid_rowconfigure(1, weight=1)
        footer = ctk.CTkFrame(flow_tab, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=16, pady=12)
        footer.grid_columnconfigure(0, weight=1)
        self.flow_id = tk.StringVar(value="system-check")
        ctk.CTkEntry(footer, textvariable=self.flow_id, width=200, placeholder_text="ID сценария").grid(row=0, column=0, sticky="w")
        action_button(footer, "Показать план", self.preview_flow, width=150).grid(row=0, column=1, padx=8)
        action_button(footer, "Сохранить JSON", self.save_flows, width=150, tone="ghost").grid(row=0, column=2, padx=8)
        action_button(footer, "Обновить", self.load_flows, width=110, tone="ghost").grid(row=0, column=3)
        action_button(footer, "Конструктор", self.open_builder, width=130).grid(row=0, column=4, padx=(8, 0))

        memory_tab = tabs.tab("Память")
        ctk.CTkLabel(memory_tab, text="Заметки: Windows DPAPI, другие ОС — без шифрования.",
                     text_color=COLORS["text_secondary"], font=FONTS["body"], anchor="w").grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))
        self.note_input = tk.StringVar()
        ctk.CTkEntry(memory_tab, textvariable=self.note_input, placeholder_text="Новая заметка").grid(row=1, column=0, sticky="ew", padx=16)
        actions = ctk.CTkFrame(memory_tab, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="w", padx=16, pady=12)
        action_button(actions, "Запомнить", self.add_note, width=150).grid(row=0, column=0, padx=(0, 8))
        action_button(actions, "Обновить список", self.show_notes, width=160, tone="ghost").grid(row=0, column=1, padx=(0, 8))
        self.note_id = tk.StringVar()
        ctk.CTkEntry(actions, textvariable=self.note_id, placeholder_text="№ заметки", width=110).grid(row=0, column=2, padx=(0, 8))
        action_button(actions, "Удалить по №", self.delete_note, width=130, tone="danger").grid(row=0, column=3)
        self.notes_output = ctk.CTkTextbox(memory_tab, font=FONTS["body"], fg_color=COLORS["input"])
        self.notes_output.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 12))
        memory_tab.grid_rowconfigure(3, weight=1)

        log_tab = tabs.tab("Журнал")
        ctk.CTkLabel(
            log_tab,
            text="Последние фоновые запуски. Повтор выполняется только после подтверждения плана.",
            font=FONTS["body"], text_color=COLORS["text_secondary"], anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        log_actions = ctk.CTkFrame(log_tab, fg_color="transparent")
        log_actions.grid(row=1, column=0, sticky="ew", padx=16, pady=8)
        self.failed_flow_id = tk.StringVar()
        ctk.CTkEntry(
            log_actions, textvariable=self.failed_flow_id, width=220,
            placeholder_text="ID неуспешного сценария"
        ).grid(row=0, column=0, padx=(0, 8))
        action_button(
            log_actions, "Показать план повтора", self.retry_failed_flow, width=190
        ).grid(row=0, column=1, padx=(0, 8))
        action_button(
            log_actions, "Обновить журнал", self.show_runs, width=150, tone="ghost"
        ).grid(row=0, column=2)
        filters = ctk.CTkFrame(log_tab, fg_color="transparent")
        filters.grid(row=2, column=0, sticky="ew", padx=16, pady=5)
        self.run_status_filter = tk.StringVar(value="Все")
        self.run_workflow_filter = tk.StringVar()
        self.run_page = 0
        self.run_page_size = 25
        ctk.CTkOptionMenu(
            filters, variable=self.run_status_filter,
            values=["Все", "Ожидает", "Успешно", "Ошибка"],
            command=lambda _value: self.reset_run_page(),
            width=135,
        ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkEntry(
            filters, textvariable=self.run_workflow_filter, width=220,
            placeholder_text="Фильтр по ID сценария",
        ).grid(row=0, column=1, padx=(0, 8))
        action_button(
            filters, "Применить фильтр", self.reset_run_page, width=145
        ).grid(row=0, column=2)

        pagination = ctk.CTkFrame(log_tab, fg_color="transparent")
        pagination.grid(row=3, column=0, sticky="ew", padx=16, pady=(3, 9))
        self.prev_run_page_button = action_button(
            pagination, "Предыдущие", lambda: self.change_run_page(-1),
            tone="ghost", width=125,
        )
        self.prev_run_page_button.grid(row=0, column=0, padx=(0, 10))
        self.run_page_label = tk.StringVar(value="Страница 1")
        ctk.CTkLabel(
            pagination, textvariable=self.run_page_label,
            text_color=COLORS["text_secondary"], font=FONTS["body"]
        ).grid(row=0, column=1)
        self.next_run_page_button = action_button(
            pagination, "Следующие", lambda: self.change_run_page(1),
            tone="ghost", width=125,
        )
        self.next_run_page_button.grid(row=0, column=2, padx=(10, 0))

        retention = ctk.CTkFrame(log_tab, fg_color="transparent")
        retention.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 7))
        self.retention_days = tk.StringVar(value="90")
        ctk.CTkEntry(
            retention, textvariable=self.retention_days, width=90,
            placeholder_text="Дней"
        ).grid(row=0, column=0, padx=(0, 7))
        action_button(
            retention, "Проверить очистку", self.preview_cleanup, width=160
        ).grid(row=0, column=1, padx=(0, 7))
        action_button(
            retention, "Подтвердить очистку", self.confirm_cleanup, width=175,
            tone="danger"
        ).grid(row=0, column=2, padx=(0, 7))
        action_button(
            retention, "Отменить очистку", self.cancel_cleanup, width=145,
            tone="ghost"
        ).grid(row=0, column=3)
        self.runs_output = ctk.CTkTextbox(
            log_tab, font=FONTS["mono"], fg_color=COLORS["input"], wrap="word"
        )
        self.runs_output.grid(row=5, column=0, sticky="nsew", padx=16, pady=(0, 12))
        log_tab.grid_rowconfigure(5, weight=1)

        self.load_flows()
        self.show_notes()
        self.show_runs()

    @staticmethod
    def _set_text(widget, text: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _run(self, command: str) -> None:
        self._set_text(self.agent_output, "Выполняется...")
        self.app.run_async(
            lambda: self.agent.handle(command),
            on_success=lambda result: self._set_text(self.agent_output, result or "Команда не найдена"),
            on_error=lambda error: self._set_text(self.agent_output, str(error)),
        )

    def propose(self) -> None:
        text = self.task.get("1.0", "end").strip()
        if text:
            self._run("агент " + text)

    def confirm(self) -> None:
        self._run("подтверди план")

    def cancel(self) -> None:
        self._run("отмени план")

    def preview_flow(self) -> None:
        identifier = self.flow_id.get().strip()
        if identifier:
            self._run("запусти сценарий " + identifier)
            self.tabs.set("ИИ-агент")

    def retry_failed_flow(self) -> None:
        identifier = self.failed_flow_id.get().strip()
        if not identifier:
            self.app.show_notice("Введите ID сценария из журнала", "warning")
            return
        self._run("повтори неудачный сценарий " + identifier)
        self.tabs.set("ИИ-агент")

    def preview_cleanup(self) -> None:
        days = self.retention_days.get().strip()
        if not days.isdigit() or not 1 <= int(days) <= 3650:
            self.app.show_notice("Укажите от 1 до 3650 дней", "warning")
            return
        self._run(f"очисти журнал старше {days} дней")
        self.tabs.set("ИИ-агент")

    def confirm_cleanup(self) -> None:
        self._run("подтверди очистку журнала")
        self.tabs.set("ИИ-агент")

    def cancel_cleanup(self) -> None:
        self._run("отмени очистку журнала")
        self.tabs.set("ИИ-агент")

    def reset_run_page(self) -> None:
        self.run_page = 0
        self.show_runs()

    def change_run_page(self, delta: int) -> None:
        self.run_page = max(0, self.run_page + delta)
        self.show_runs()

    def show_runs(self) -> None:
        try:
            status_options = {
                "Все": None, "Ожидает": "claimed",
                "Успешно": "succeeded", "Ошибка": "failed",
            }
            status = status_options[self.run_status_filter.get()]
            workflow_id = self.run_workflow_filter.get().strip() or None
            total = self.agent.store.count_scheduled_runs(
                status=status, workflow_id=workflow_id,
            )
            page_count = max(1, (total + self.run_page_size - 1) // self.run_page_size)
            self.run_page = min(self.run_page, page_count - 1)
            rows = self.agent.store.list_scheduled_runs(
                limit=self.run_page_size, status=status, workflow_id=workflow_id,
                offset=self.run_page * self.run_page_size,
            )
            records = [
                f"{datetime.fromtimestamp(item['claimed']).strftime('%Y-%m-%d %H:%M:%S')} "
                f"| {item['workflow_id']} | {item['status']}"
                + (" [ТРЕБУЕТ ПРОВЕРКИ: " + describe_claim(
                    item, current_session=self.agent.workflows.owner_session
                ) + "]" if item["needs_review"] else "")
                + f" | {item['run_key']}\n  {item['detail'][:200]}"
                for item in rows
            ]
            self.run_page_label.set(
                f"Страница {self.run_page + 1} из {page_count}, записей: {total}"
            )
            self.prev_run_page_button.configure(
                state="normal" if self.run_page > 0 else "disabled"
            )
            self.next_run_page_button.configure(
                state="normal" if self.run_page + 1 < page_count else "disabled"
            )
            self._set_text(self.runs_output, "\n\n".join(records) or "Запусков не найдено.")
        except Exception as error:
            self._set_text(self.runs_output, f"Не удалось прочитать журнал: {error}")

    def load_flows(self) -> None:
        path = self.agent.workflows.path
        if path.exists():
            raw = path.read_text(encoding="utf-8")
        else:
            template = path.with_name("garfield_workflows.json.example")
            raw = template.read_text(encoding="utf-8") if template.exists() else '{"workflows":[]}'
        self.flow_json.configure(state="normal")
        self.flow_json.delete("1.0", "end")
        self.flow_json.insert("1.0", raw)

    def open_builder(self) -> None:
        try:
            WorkflowBuilder(
                self,
                self.flow_json.get("1.0", "end").strip(),
                self.agent.runner,
                self._apply_builder_json,
            )
        except Exception as error:
            self.app.show_notice(f"Ошибка конструктора: {error}", "danger")

    def _apply_builder_json(self, content: str) -> None:
        self.flow_json.configure(state="normal")
        self.flow_json.delete("1.0", "end")
        self.flow_json.insert("1.0", content)
        self.app.show_notice("Изменения показаны в JSON. Нажмите «Сохранить JSON».", "success")

    def save_flows(self) -> None:
        path = self.agent.workflows.path
        raw = self.flow_json.get("1.0", "end").strip()
        temporary = None
        try:
            json.loads(raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", prefix=".garfield-", dir=path.parent, delete=False) as file:
                temporary = Path(file.name)
                file.write(raw + "\n")
            # Only validated workflows are allowed onto disk.
            WorkflowLibrary(temporary, self.agent.runner).all()
            os.replace(temporary, path)
            self.app.show_notice("Сценарии проверены и сохранены", "success")
        except Exception as error:
            self.app.show_notice(f"Ошибка сценария: {error}", "danger")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def show_notes(self) -> None:
        rows = self.agent.store.notes(limit=50)
        self._set_text(self.notes_output, "\n".join(f"#{x['id']}: {x['content']}" for x in rows) or "Пока заметок нет")

    def add_note(self) -> None:
        value = self.note_input.get().strip()
        if not value:
            return
        try:
            self.agent.store.add_note(value)
            self.note_input.set("")
            self.show_notes()
        except Exception as error:
            self.app.show_notice(str(error), "danger")

    def delete_note(self) -> None:
        value = self.note_id.get().strip()
        if not value.isdigit():
            self.app.show_notice("Введите номер заметки", "warning")
            return
        self.agent.store.delete_note(int(value))
        self.note_id.set("")
        self.show_notes()

    def on_show(self) -> None:
        self.show_notes()
        self.show_runs()
