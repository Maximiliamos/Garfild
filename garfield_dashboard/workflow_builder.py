"""Visual editor for declarative workflow steps: drag rows to change ordering.

The editor does not execute workflows. Applying changes only updates the JSON
in the existing Automation page; user must then save explicitly.
"""
from __future__ import annotations

import json
import re
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from garfield_agent.workflow_editor import delete_step, move_step, replace_step
from .theme import COLORS, FONTS


class WorkflowBuilder(ctk.CTkToplevel):
    def __init__(self, parent, raw: str, runner, on_apply):
        super().__init__(parent)
        self.title("Конструктор сценариев Garfield")
        self.geometry("820x690")
        self.minsize(720, 600)
        self.configure(fg_color=COLORS["background"])
        self.transient(parent)
        self.grab_set()
        self.runner = runner
        self.on_apply = on_apply
        self.data = json.loads(raw)
        self.flows = self.data.get("workflows", [])
        if not isinstance(self.flows, list):
            raise ValueError("Неверный формат workflows")
        self.steps = []
        self.drag_iid = None
        self.current_flow_id = None
        self.loaded_snapshot = None
        self.selector = tk.StringVar()
        self.identifier = tk.StringVar()
        self.label = tk.StringVar()
        self.schedule = tk.StringVar()
        self.trigger = tk.StringVar()
        self.tool = tk.StringVar(value="system_status")
        self.arguments = tk.StringVar(value="{}")
        self.status = tk.StringVar(value="Перетащите строку мышью для изменения порядка.")

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=12)
        names = [f.get("id", "") for f in self.flows] + ["(новый)"]
        ctk.CTkOptionMenu(header, values=names, variable=self.selector, command=self.load_flow,
                          width=220).pack(side="left", padx=(0, 10))
        self.selector.set(names[0])
        ctk.CTkLabel(header, textvariable=self.status, text_color=COLORS["text_secondary"],
                     font=FONTS["small"]).pack(side="left")

        form = ctk.CTkFrame(self, fg_color=COLORS["surface"])
        form.pack(fill="x", padx=16)
        for row, (name, variable) in enumerate([
            ("ID", self.identifier), ("Название", self.label),
            ("Ежедневно (HH:MM)", self.schedule), ("При создании файла в workspace", self.trigger),
        ]):
            ctk.CTkLabel(form, text=name, text_color=COLORS["text"], width=240,
                         anchor="w").grid(row=row, column=0, padx=12, pady=6, sticky="w")
            ctk.CTkEntry(form, textvariable=variable, width=445).grid(row=row, column=1, pady=6, sticky="ew")
        form.grid_columnconfigure(1, weight=1)

        self.table = ttk.Treeview(self, columns=("tool", "args"), show="headings", selectmode="browse", height=9)
        self.table.heading("tool", text="Инструмент")
        self.table.heading("args", text="Аргументы")
        self.table.column("tool", width=180, stretch=False)
        self.table.column("args", width=545)
        self.table.pack(fill="both", expand=True, padx=16, pady=12)
        self.table.bind("<<TreeviewSelect>>", self.populate_selected)
        self.table.bind("<ButtonPress-1>", self.drag_start)
        self.table.bind("<B1-Motion>", self.drag_move)
        self.table.bind("<ButtonRelease-1>", self.drag_end)

        item = ctk.CTkFrame(self, fg_color="transparent")
        item.pack(fill="x", padx=16, pady=5)
        tools = sorted(self.runner.tools.SPECS)
        ctk.CTkOptionMenu(item, values=tools, variable=self.tool, width=210).grid(row=0, column=0, padx=5)
        ctk.CTkEntry(item, textvariable=self.arguments, placeholder_text="Аргументы JSON", width=420).grid(
            row=0, column=1, padx=5, sticky="ew"
        )
        item.grid_columnconfigure(1, weight=1)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=8)
        for i, (label, fn) in enumerate([
            ("Добавить шаг", self.add_step), ("Изменить", self.update_step),
            ("Удалить", self.remove_step), ("↑", lambda: self.move(-1)),
            ("↓", lambda: self.move(1)), ("Применить к JSON", self.apply),
        ]):
            ctk.CTkButton(actions, text=label, command=fn, width=90).grid(row=0, column=i, padx=4, sticky="ew")
            actions.grid_columnconfigure(i, weight=1)
        self.load_flow(names[0])

    def _snapshot(self):
        return (
            self.identifier.get(), self.label.get(), self.schedule.get(),
            self.trigger.get(), json.dumps(self.steps, ensure_ascii=False, sort_keys=True),
        )

    def load_flow(self, identifier: str):
        if (self.current_flow_id is not None and identifier != self.current_flow_id
                and self.loaded_snapshot != self._snapshot()):
            self.selector.set(self.current_flow_id)
            self.status.set("Есть несохранённые изменения. Сначала примените их к JSON.")
            return
        self.steps = []
        found = next((f for f in self.flows if f.get("id") == identifier), None)
        self.identifier.set(found.get("id", "") if found else "")
        self.label.set(found.get("name", "") if found else "")
        self.schedule.set(found.get("daily_at") or "" if found else "")
        self.trigger.set(found.get("when_file_created") or "" if found else "")
        if found:
            self.steps = [dict(step) for step in found["steps"]]
        self.current_flow_id = identifier
        self.loaded_snapshot = self._snapshot()
        self.refresh()

    def refresh(self):
        for item in self.table.get_children():
            self.table.delete(item)
        for step in self.steps:
            self.table.insert("", "end", values=(step["tool"], json.dumps(step["args"], ensure_ascii=False)))

    def selected_index(self):
        selected = self.table.selection()
        if not selected:
            raise ValueError("Выберите строку")
        return self.table.index(selected[0])

    def populate_selected(self, _event=None):
        try:
            step = self.steps[self.selected_index()]
        except (ValueError, IndexError):
            return
        self.tool.set(step["tool"])
        self.arguments.set(json.dumps(step["args"], ensure_ascii=False))

    def read_step(self):
        args = json.loads(self.arguments.get())
        step = {"tool": self.tool.get(), "args": args}
        self.runner.validate_steps([step])
        return step

    def add_step(self):
        try:
            if len(self.steps) >= 6:
                raise ValueError("Максимум 6 шагов")
            self.steps.append(self.read_step())
            self.refresh()
        except Exception as e:
            self.status.set("Ошибка: " + str(e)[:120])

    def update_step(self):
        try:
            index = self.selected_index()
            self.steps = replace_step(self.steps, index, self.read_step())
            self.refresh()
        except Exception as e:
            self.status.set("Ошибка: " + str(e)[:120])

    def remove_step(self):
        try:
            self.steps = delete_step(self.steps, self.selected_index())
            self.refresh()
        except Exception as e:
            self.status.set(str(e))

    def move(self, offset):
        try:
            old = self.selected_index()
            target = old + offset
            self.steps = move_step(self.steps, old, target)
            self.refresh()
            iid = self.table.get_children()[target]
            self.table.selection_set(iid)
        except (ValueError, IndexError) as e:
            self.status.set(str(e))

    def drag_start(self, event):
        self.drag_iid = self.table.identify_row(event.y)

    def drag_move(self, event):
        target = self.table.identify_row(event.y)
        if self.drag_iid and target and target != self.drag_iid:
            old = self.table.index(self.drag_iid)
            new = self.table.index(target)
            self.steps = move_step(self.steps, old, new)
            self.table.move(self.drag_iid, "", new)
            self.table.selection_set(self.drag_iid)

    def drag_end(self, _event):
        self.drag_iid = None

    def apply(self):
        try:
            identifier = self.identifier.get().strip()
            if not re.fullmatch("[a-z0-9_-]{1,40}", identifier):
                raise ValueError("ID: латинские строчные буквы, цифры, _ и -")
            steps = self.runner.validate_steps(self.steps)
            schedule = self.schedule.get().strip() or None
            watched = self.trigger.get().strip() or None
            if schedule and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", schedule):
                raise ValueError("Время: HH:MM")
            if schedule and watched:
                raise ValueError("Выберите одно условие запуска")
            if watched:
                self.runner.tools._within_workspace(watched)
            current = self.selector.get()
            if any(flow.get("id") == identifier and flow.get("id") != current for flow in self.flows):
                raise ValueError("Такой ID уже используется")
            flow = {
                "id": identifier, "name": self.label.get().strip() or identifier,
                "steps": steps, "daily_at": schedule, "when_file_created": watched,
            }
            if current == "(новый)":
                self.flows.append(flow)
            else:
                index = next(i for i, candidate in enumerate(self.flows) if candidate["id"] == current)
                self.flows[index] = flow
            self.on_apply(json.dumps({"workflows": self.flows}, ensure_ascii=False, indent=2))
            self.destroy()
        except Exception as error:
            self.status.set("Ошибка: " + str(error)[:140])
