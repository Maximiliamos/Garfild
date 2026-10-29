"""Agent and workflow controls with explicit confirmation and JSON validation."""
from __future__ import annotations

import json
import os
import tempfile
import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from garfield_agent.runner import WorkflowLibrary
from ..components import action_button, card
from ..theme import COLORS, FONTS


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
        for name in ("ИИ-агент", "Сценарии", "Память"):
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

        memory_tab = tabs.tab("Память")
        ctk.CTkLabel(memory_tab, text="Заметки хранятся локально. Данные не шифруются.",
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
        self.load_flows()
        self.show_notes()

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
