"""Built-in command catalog page."""

from __future__ import annotations

import customtkinter as ctk

import garfield_best as core

from ..components import action_button, card
from ..theme import COLORS, FONTS


class CommandsPage(ctk.CTkFrame):
    def __init__(self, parent, adapter, app) -> None:
        super().__init__(parent, fg_color="transparent")
        self.adapter = adapter
        self.app = app

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = card(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Команды", anchor="w", text_color=COLORS["text"], font=FONTS["title"]).grid(
            row=0,
            column=0,
            sticky="ew",
            padx=18,
            pady=(16, 2),
        )
        ctk.CTkLabel(
            top,
            text="Встроенные голосовые сценарии для браузера, Windows, текста, мыши и режима ассистента.",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["body"],
            wraplength=820,
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))
        action_button(top, "Озвучить список", lambda: self.adapter.submit_command("список команд"), width=150).grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
            padx=18,
            pady=16,
        )

        self.catalog = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.catalog.grid(row=1, column=0, sticky="nsew")
        for col in range(2):
            self.catalog.grid_columnconfigure(col, weight=1, uniform="commands")

        self.render()

    def render(self) -> None:
        for child in self.catalog.winfo_children():
            child.destroy()

        for index, (title, commands) in enumerate(core.command_catalog()):
            group = card(self.catalog)
            group.grid(row=index // 2, column=index % 2, sticky="nsew", padx=6, pady=6)
            group.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                group,
                text=title,
                anchor="w",
                text_color=COLORS["accent"],
                font=FONTS["section"],
            ).grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))

            for row, command in enumerate(commands, start=1):
                item = ctk.CTkFrame(group, fg_color=COLORS["surface_alt"], corner_radius=8)
                item.grid(row=row, column=0, sticky="ew", padx=12, pady=3)
                item.grid_columnconfigure(0, weight=1)
                ctk.CTkLabel(
                    item,
                    text=command,
                    anchor="w",
                    justify="left",
                    text_color=COLORS["text"],
                    font=FONTS["body"],
                    wraplength=420,
                ).grid(row=0, column=0, sticky="ew", padx=10, pady=8)
