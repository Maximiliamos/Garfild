"""Reusable CustomTkinter widgets used by the dashboard pages."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from .theme import COLORS, FONTS, TONE_BG, TONE_COLOR


def card(parent, **grid_kwargs) -> ctk.CTkFrame:
    frame = ctk.CTkFrame(
        parent,
        fg_color=COLORS["surface"],
        border_width=1,
        border_color=COLORS["border"],
        corner_radius=8,
    )
    if grid_kwargs:
        frame.grid(**grid_kwargs)
    return frame


def action_button(
    parent,
    text: str,
    command: Callable[[], None],
    *,
    tone: str = "primary",
    width: int | None = None,
) -> ctk.CTkButton:
    if tone == "danger":
        fg_color = COLORS["danger"]
        hover_color = "#E11D48"
        text_color = "#FFFFFF"
    elif tone == "ghost":
        fg_color = COLORS["surface_alt"]
        hover_color = COLORS["muted"]
        text_color = COLORS["text"]
    else:
        fg_color = COLORS["accent"]
        hover_color = COLORS["accent_hover"]
        text_color = "#FFFFFF"

    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        width=width if width is not None else 120,
        height=36,
        corner_radius=8,
        fg_color=fg_color,
        hover_color=hover_color,
        text_color=text_color,
        font=FONTS["body_bold"],
    )


class StatusPill(ctk.CTkFrame):
    def __init__(self, parent, text: str = "", tone: str = "muted", width: int = 320) -> None:
        super().__init__(
            parent,
            width=width,
            height=30,
            fg_color=TONE_BG.get(tone, TONE_BG["muted"]),
            corner_radius=999,
            border_width=0,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self._label_width = max(80, width - 48)
        self.dot = ctk.CTkLabel(
            self,
            text="●",
            text_color=TONE_COLOR.get(tone, TONE_COLOR["muted"]),
            font=("Segoe UI", 13, "bold"),
            width=18,
        )
        self.dot.grid(row=0, column=0, padx=(10, 0), pady=5)
        self.label = ctk.CTkLabel(
            self,
            text=text,
            width=self._label_width,
            anchor="w",
            text_color=COLORS["text"],
            font=FONTS["small"],
        )
        self.label.grid(row=0, column=1, sticky="ew", padx=(2, 12), pady=5)
        self.set(text, tone)

    def set(self, text: str, tone: str = "muted") -> None:
        display_text = text if len(text) <= 64 else f"{text[:61]}..."
        self.configure(fg_color=TONE_BG.get(tone, TONE_BG["muted"]))
        self.dot.configure(text_color=TONE_COLOR.get(tone, TONE_COLOR["muted"]))
        self.label.configure(text=display_text)


class MetricCard(ctk.CTkFrame):
    def __init__(self, parent, title: str, value: str = "", tone: str = "muted") -> None:
        super().__init__(
            parent,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
        )
        self.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        top.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            top,
            text=title,
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["small"],
        )
        self.title_label.grid(row=0, column=0, sticky="ew")
        self.dot = ctk.CTkLabel(
            top,
            text="●",
            text_color=TONE_COLOR.get(tone, TONE_COLOR["muted"]),
            font=("Segoe UI", 14, "bold"),
            width=18,
        )
        self.dot.grid(row=0, column=1, sticky="e")

        self.value_label = ctk.CTkLabel(
            self,
            text=value,
            anchor="w",
            justify="left",
            text_color=COLORS["text"],
            font=FONTS["body_bold"],
            wraplength=260,
        )
        self.value_label.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))
        self.set(value, tone)

    def set(self, value: str, tone: str = "muted") -> None:
        self.value_label.configure(text=value)
        self.dot.configure(text_color=TONE_COLOR.get(tone, TONE_COLOR["muted"]))


class ConfirmDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        title: str,
        message: str,
        on_confirm: Callable[[], None],
        *,
        confirm_text: str = "Подтвердить",
        danger: bool = False,
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.geometry("440x220")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["background"])
        self.transient(parent)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self,
            text=title,
            anchor="w",
            text_color=COLORS["text"],
            font=FONTS["title"],
        ).grid(row=0, column=0, sticky="ew", padx=22, pady=(22, 8))
        ctk.CTkLabel(
            self,
            text=message,
            anchor="w",
            justify="left",
            text_color=COLORS["text_secondary"],
            font=FONTS["body"],
            wraplength=390,
        ).grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 18))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", padx=22, pady=(8, 22))
        buttons.grid_columnconfigure(0, weight=1)

        def confirm() -> None:
            self.destroy()
            on_confirm()

        action_button(buttons, "Отмена", self.destroy, tone="ghost", width=110).grid(row=0, column=1, padx=(0, 10))
        action_button(
            buttons,
            confirm_text,
            confirm,
            tone="danger" if danger else "primary",
            width=135,
        ).grid(row=0, column=2)


def labeled_input(parent, label: str, row: int, variable, *, show: str | None = None):
    ctk.CTkLabel(parent, text=label, anchor="w", text_color=COLORS["text"], font=FONTS["body_bold"]).grid(
        row=row,
        column=0,
        sticky="w",
        padx=(0, 16),
        pady=8,
    )
    entry = ctk.CTkEntry(
        parent,
        textvariable=variable,
        show=show,
        fg_color=COLORS["input"],
        border_color=COLORS["border"],
        border_width=1,
        corner_radius=8,
        height=36,
        text_color=COLORS["text"],
        font=FONTS["body"],
    )
    entry.grid(row=row, column=1, sticky="ew", pady=8)
    return entry
