"""Runtime diagnostics dashboard page."""

from __future__ import annotations

import customtkinter as ctk

from ..components import MetricCard, action_button, card
from ..theme import COLORS, FONTS


class DiagnosticsPage(ctk.CTkFrame):
    def __init__(self, parent, adapter, app) -> None:
        super().__init__(parent, fg_color="transparent")
        self.adapter = adapter
        self.app = app
        self.cards: list[MetricCard] = []
        self.loading = False
        self.loaded_once = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = card(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Диагностика", anchor="w", text_color=COLORS["text"], font=FONTS["title"]).grid(
            row=0,
            column=0,
            sticky="ew",
            padx=18,
            pady=(16, 2),
        )
        ctk.CTkLabel(
            top,
            text="Актуальное состояние моделей, API, аудио, памяти и команд.",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["body"],
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))

        self.grid_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.grid_frame.grid(row=1, column=0, sticky="nsew")
        for col in range(4):
            self.grid_frame.grid_columnconfigure(col, weight=1, uniform="diagnostics")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        for col in range(3):
            actions.grid_columnconfigure(col, weight=1)
        buttons = [
            ("Обновить статус", self.refresh, "primary"),
            ("Очистить память диалога", self.clear_memory, "ghost"),
            ("Очистить кэш", self.clear_cache, "ghost"),
            ("Открыть папку проекта", self.open_project_folder, "ghost"),
            ("Открыть лог", self.open_log, "ghost"),
        ]
        for index, (text, command, tone) in enumerate(buttons):
            action_button(actions, text, command, tone=tone, width=150).grid(
                row=index // 3,
                column=index % 3,
                sticky="ew",
                padx=4,
                pady=4,
            )

    def on_show(self) -> None:
        if not self.loaded_once and not self.loading:
            self.refresh(log=False)

    def refresh(self, log: bool = True) -> None:
        if self.loading:
            return
        self.loading = True

        def success(items) -> None:
            self._render_items(items)
            self.loading = False
            self.loaded_once = True
            if log:
                self.adapter.log_action("Диагностика обновлена.")

        def failure(error: Exception) -> None:
            self.loading = False
            self.app.show_notice(f"Не удалось обновить диагностику: {error}", "danger")

        self.app.run_async(self.adapter.diagnostics, on_success=success, on_error=failure)

    def _render_items(self, items) -> None:
        for item in self.cards:
            item.destroy()
        self.cards = []
        for index, item in enumerate(items):
            widget = MetricCard(self.grid_frame, item.title, item.value, item.tone)
            widget.grid(row=index // 4, column=index % 4, sticky="nsew", padx=5, pady=5)
            self.cards.append(widget)

    def clear_memory(self) -> None:
        self.adapter.clear_dialog_memory()
        self.app.show_notice("Память диалога очищена.", "success")
        self.adapter.log_action("Память диалога очищена через диагностику.")
        self.refresh()

    def clear_cache(self) -> None:
        self.adapter.clear_answer_cache()
        self.app.show_notice("Кэш ответов очищен.", "success")
        self.adapter.log_action("Кэш ответов очищен через диагностику.")
        self.refresh()

    def open_project_folder(self) -> None:
        try:
            self.app.show_notice(self.adapter.open_project_folder(), "success")
            self.adapter.log_action("Открыта папка проекта.")
        except Exception as error:
            self.app.show_notice(f"Не удалось открыть папку проекта: {error}", "danger")

    def open_log(self) -> None:
        try:
            self.app.show_notice(self.adapter.open_log_file(), "success")
            self.adapter.log_action("Открыт лог приложения.")
        except Exception as error:
            self.app.show_notice(f"Не удалось открыть лог: {error}", "danger")
