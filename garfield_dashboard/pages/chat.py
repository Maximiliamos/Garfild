"""Chat page for text commands and live runtime events."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import tkinter as tk

import customtkinter as ctk

from ..components import StatusPill, action_button, card
from ..theme import COLORS, FONTS


class ChatPage(ctk.CTkFrame):
    def __init__(self, parent, adapter, app) -> None:
        super().__init__(parent, fg_color="transparent")
        self.adapter = adapter
        self.app = app
        self.message_rows: list[ctk.CTkFrame] = []
        self.input_var = tk.StringVar()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        status_card = card(self)
        status_card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        status_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            status_card,
            text="Garfield Flagship",
            anchor="w",
            text_color=COLORS["text"],
            font=FONTS["display"],
        ).grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 2))
        self.subtitle = ctk.CTkLabel(
            status_card,
            text="Готовлю ассистента к работе...",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["body"],
            wraplength=620,
        )
        self.subtitle.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))

        pills = ctk.CTkFrame(status_card, fg_color="transparent")
        pills.grid(row=0, column=1, rowspan=2, sticky="e", padx=18, pady=16)
        self.listening_pill = StatusPill(pills, "Прослушивание выключено", "muted")
        self.listening_pill.grid(row=0, column=0, padx=(0, 8))
        self.tts_pill = StatusPill(pills, "Озвучка включена", "success")
        self.tts_pill.grid(row=0, column=1)

        chat_card = card(self)
        chat_card.grid(row=1, column=0, sticky="nsew")
        chat_card.grid_columnconfigure(0, weight=1)
        chat_card.grid_rowconfigure(0, weight=1)

        self.messages = ctk.CTkScrollableFrame(
            chat_card,
            fg_color=COLORS["surface"],
            corner_radius=8,
        )
        self.messages.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.messages.grid_columnconfigure(0, weight=1)

        composer = ctk.CTkFrame(chat_card, fg_color="transparent")
        composer.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        composer.grid_columnconfigure(0, weight=1)
        entry = ctk.CTkEntry(
            composer,
            textvariable=self.input_var,
            placeholder_text="Введите команду или вопрос...",
            height=42,
            fg_color=COLORS["input"],
            border_color=COLORS["border"],
            border_width=1,
            corner_radius=8,
            font=FONTS["body"],
        )
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        entry.bind("<Return>", lambda _event: self.submit_manual())
        action_button(composer, "Отправить", self.submit_manual, width=120).grid(row=0, column=1)

        quick = ctk.CTkFrame(self, fg_color="transparent")
        quick.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        for index in range(4):
            quick.grid_columnconfigure(index, weight=1)

        buttons = [
            ("Старт прослушивания", self.start_listening, "primary"),
            ("Стоп прослушивания", self.stop_listening, "ghost"),
            ("Помощь", lambda: self.submit_command("помощь"), "ghost"),
            ("Повтори", lambda: self.submit_command("повтори"), "ghost"),
            ("Статус", lambda: self.submit_command("диагностика"), "ghost"),
            ("Сохранить диалог", lambda: self.submit_command("сохрани диалог"), "ghost"),
            ("Очистить кэш", lambda: self.submit_command("очисти кэш"), "ghost"),
            ("Выход", self.app.confirm_exit, "danger"),
        ]
        for index, (text, command, tone) in enumerate(buttons):
            action_button(quick, text, command, tone=tone, width=150).grid(
                row=index // 4,
                column=index % 4,
                sticky="ew",
                padx=4,
                pady=4,
            )

    def update_state(self) -> None:
        listening = self.adapter.runtime.listening_enabled
        tts_enabled = self.adapter.runtime.tts.enabled
        self.listening_pill.set(
            "Прослушивание включено" if listening else "Прослушивание выключено",
            "success" if listening else "muted",
        )
        self.tts_pill.set(
            "Озвучка включена" if tts_enabled else "Озвучка выключена",
            "success" if tts_enabled else "muted",
        )

    def set_status(self, text: str) -> None:
        self.subtitle.configure(text=text)

    def submit_manual(self) -> None:
        text = self.input_var.get().strip()
        if not text:
            return
        self.input_var.set("")
        self.submit_command(text, source="manual")

    def submit_command(self, text: str, source: str = "gui") -> None:
        self.adapter.submit_command(text, source=source)

    def start_listening(self) -> None:
        self.adapter.log_action("Кнопка: старт прослушивания.")
        self.app.run_async(
            lambda: self.adapter.set_listening(True),
            on_success=lambda _result: (self.update_state(), self.app._update_sidebar_voice_state()),
            on_error=lambda error: self.app.show_notice(f"Не удалось включить прослушивание: {error}", "danger"),
        )

    def stop_listening(self) -> None:
        self.adapter.log_action("Кнопка: стоп прослушивания.")
        self.app.run_async(
            lambda: self.adapter.set_listening(False),
            on_success=lambda _result: (self.update_state(), self.app._update_sidebar_voice_state()),
            on_error=lambda error: self.app.show_notice(f"Не удалось выключить прослушивание: {error}", "danger"),
        )

    def add_event(self, event: Any) -> None:
        role = getattr(event, "kind", "status")
        text = getattr(event, "text", "")
        created_at = getattr(event, "created_at", None)
        timestamp = datetime.fromtimestamp(created_at).strftime("%H:%M:%S") if created_at else datetime.now().strftime("%H:%M:%S")
        if role == "status":
            self.set_status(text)
        self._add_message(role, text, timestamp)
        self.update_state()

    def _add_message(self, role: str, text: str, timestamp: str) -> None:
        row = ctk.CTkFrame(self.messages, fg_color="transparent")
        row.grid(row=len(self.message_rows), column=0, sticky="ew", padx=4, pady=5)
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=1)

        role_label = {
            "assistant": "Гарфилд",
            "user": "Вы",
            "status": "Система",
            "progress": "Гарфилд",
        }.get(role, role.title())
        bubble_color = {
            "assistant": COLORS["surface_alt"],
            "user": COLORS["accent_soft"],
            "status": COLORS["muted"],
            "progress": COLORS["warning_soft"],
        }.get(role, COLORS["surface_alt"])
        column = 1 if role == "user" else 0
        sticky = "e" if role == "user" else "w"

        bubble = ctk.CTkFrame(row, fg_color=bubble_color, corner_radius=8)
        bubble.grid(row=0, column=column, sticky=sticky, padx=(80, 0) if role == "user" else (0, 80))
        bubble.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            bubble,
            text=f"{role_label} · {timestamp}",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["small"],
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(9, 0))
        ctk.CTkLabel(
            bubble,
            text=text,
            anchor="w",
            justify="left",
            text_color=COLORS["text"],
            font=FONTS["body"],
            wraplength=560,
        ).grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 10))

        self.message_rows.append(row)
        self.after(20, self._scroll_to_bottom)
        self.after(90, self._scroll_to_bottom)
        self.after_idle(self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        try:
            self.update_idletasks()
            self.messages._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass
