"""Session history page."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any

import customtkinter as ctk

from ..components import ConfirmDialog, action_button, card
from ..theme import COLORS, FONTS


@dataclass
class HistoryItem:
    role: str
    text: str
    timestamp: str
    sensitive: bool = False
    persist: bool = True


class HistoryPage(ctk.CTkFrame):
    def __init__(self, parent, adapter, app) -> None:
        super().__init__(parent, fg_color="transparent")
        self.adapter = adapter
        self.app = app
        self.items: list[HistoryItem] = []
        self.rows: list[ctk.CTkFrame] = []
        self.filter_var = tk.StringVar(value="Все")
        self.search_var = tk.StringVar()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = card(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(top, text="История", anchor="w", text_color=COLORS["text"], font=FONTS["title"]).grid(
            row=0,
            column=0,
            sticky="w",
            padx=18,
            pady=(16, 2),
        )
        ctk.CTkLabel(
            top,
            text="Сообщения текущей сессии с фильтрацией и экспортом.",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["body"],
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))

        ctk.CTkSegmentedButton(
            top,
            values=["Все", "Пользователь", "Гарфилд", "Система"],
            variable=self.filter_var,
            command=lambda _value: self.render(),
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["surface_alt"],
            unselected_hover_color=COLORS["muted"],
            text_color=COLORS["text"],
        ).grid(row=0, column=1, rowspan=2, sticky="e", padx=18, pady=16)

        body = card(self)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        search = ctk.CTkEntry(
            body,
            textvariable=self.search_var,
            placeholder_text="Поиск по истории...",
            height=38,
            fg_color=COLORS["input"],
            border_color=COLORS["border"],
            border_width=1,
            corner_radius=8,
            font=FONTS["body"],
        )
        search.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        search.bind("<KeyRelease>", lambda _event: self.render())

        self.list_frame = ctk.CTkScrollableFrame(body, fg_color=COLORS["surface"], corner_radius=8)
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.list_frame.grid_columnconfigure(0, weight=1)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(0, weight=1)
        action_button(actions, "Сохранить историю", self.save_history, tone="ghost", width=160).grid(row=0, column=1, padx=(0, 10))
        action_button(actions, "Очистить текущий экран", self.clear_screen, tone="ghost", width=180).grid(row=0, column=2, padx=(0, 10))
        action_button(actions, "Удалить историю с диска", self.delete_saved_history, tone="danger", width=190).grid(row=0, column=3, padx=(0, 10))
        action_button(actions, "Экспортировать", self.export_history, width=160).grid(row=0, column=4)

    def add_event(self, event: Any) -> None:
        role = getattr(event, "kind", "status")
        text = getattr(event, "text", "")
        created_at = getattr(event, "created_at", None)
        timestamp = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S") if created_at else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.items.append(
            HistoryItem(
                role,
                text,
                timestamp,
                sensitive=bool(getattr(event, "sensitive", False)),
                persist=bool(getattr(event, "persist", True)),
            )
        )
        self.render()

    def render(self) -> None:
        for row in self.rows:
            row.destroy()
        self.rows = []
        query = self.search_var.get().strip().lower()
        selected = self.filter_var.get()
        role_map = {"Пользователь": "user", "Гарфилд": "assistant", "Система": "status"}

        filtered = []
        for item in self.items:
            if selected != "Все" and item.role != role_map.get(selected):
                continue
            if query and query not in item.text.lower():
                continue
            filtered.append(item)

        for index, item in enumerate(filtered):
            self._add_row(index, item)

    def _add_row(self, index: int, item: HistoryItem) -> None:
        row = ctk.CTkFrame(self.list_frame, fg_color=COLORS["surface_alt"], corner_radius=8)
        row.grid(row=index, column=0, sticky="ew", pady=4)
        row.grid_columnconfigure(1, weight=1)
        label = {"assistant": "Гарфилд", "user": "Вы", "status": "Система", "progress": "Ход"}.get(item.role, item.role)
        tone = {"assistant": COLORS["accent"], "user": COLORS["success"], "status": COLORS["warning"], "progress": COLORS["warning"]}.get(item.role, COLORS["text_secondary"])
        ctk.CTkLabel(row, text=label, text_color=tone, font=FONTS["body_bold"], width=90, anchor="w").grid(
            row=0,
            column=0,
            sticky="nw",
            padx=12,
            pady=10,
        )
        ctk.CTkLabel(row, text=item.text, text_color=COLORS["text"], font=FONTS["body"], anchor="w", justify="left", wraplength=700).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 12),
            pady=(10, 2),
        )
        ctk.CTkLabel(row, text=item.timestamp, text_color=COLORS["text_secondary"], font=FONTS["small"], anchor="w").grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 12),
            pady=(0, 10),
        )
        self.rows.append(row)

    def save_history(self) -> None:
        try:
            path = self.adapter.save_session_history()
            self.app.show_notice(f"История сохранена в {path.name}.", "success")
            self.adapter.log_action("История сессии сохранена.")
        except Exception as error:
            self.app.show_notice(f"Не удалось сохранить историю: {error}", "danger")

    def clear_screen(self) -> None:
        self.items.clear()
        self.adapter.clear_session_history()
        self.render()
        self.app.show_notice("Текущий экран истории очищен.", "success")
        self.adapter.log_action("Текущий экран истории очищен.")

    def delete_saved_history(self) -> None:
        def delete() -> None:
            deleted = self.adapter.delete_saved_history()
            self.app.show_notice(
                f"Удалено файлов истории: {len(deleted)}.",
                "warning",
            )
            self.adapter.log_action("Сохранённая история удалена с диска.")

        ConfirmDialog(
            self,
            "Удалить сохранённую историю",
            "Удалить основную историю и все TXT/JSON-экспорты с диска?",
            delete,
            confirm_text="Удалить",
            danger=True,
        )

    def export_history(self) -> None:
        try:
            self.adapter.export_history([asdict(item) for item in self.items])
            self.app.show_notice("История экспортирована в TXT и JSON.", "success")
            self.adapter.log_action("История экспортирована в TXT и JSON.")
        except Exception as error:
            self.app.show_notice(f"Не удалось экспортировать историю: {error}", "danger")
