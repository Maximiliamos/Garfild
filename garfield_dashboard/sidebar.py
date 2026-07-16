"""Left navigation rail for the dashboard."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from .components import StatusPill
from .theme import APP_TITLE, APP_VERSION, COLORS, FONTS


NAV_ITEMS = [
    ("chat", "Чат"),
    ("commands", "Команды"),
    ("voice", "Голос"),
    ("audio", "Звук"),
    ("skills", "Навыки"),
    ("diagnostics", "Диагностика"),
    ("settings", "Настройки"),
    ("history", "История"),
]


class Sidebar(ctk.CTkFrame):
    def __init__(
        self,
        parent,
        on_select: Callable[[str], None],
        on_toggle_listening: Callable[[], None],
        on_toggle_tts: Callable[[], None],
        on_toggle_bundle: Callable[[], None],
    ) -> None:
        super().__init__(
            parent,
            width=240,
            fg_color=COLORS["sidebar"],
            corner_radius=0,
        )
        self.grid_propagate(False)
        self.on_select = on_select
        self.on_toggle_listening = on_toggle_listening
        self.on_toggle_tts = on_toggle_tts
        self.on_toggle_bundle = on_toggle_bundle
        self.buttons: dict[str, ctk.CTkButton] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 14))
        brand.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            brand,
            text=APP_TITLE,
            anchor="w",
            text_color=COLORS["text"],
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            brand,
            text="AI ассистент",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["small"],
        ).grid(row=1, column=0, sticky="ew", pady=(2, 0))

        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 0))
        nav.grid_columnconfigure(0, weight=1)

        for row, (key, label) in enumerate(NAV_ITEMS):
            button = ctk.CTkButton(
                nav,
                text=label,
                height=40,
                anchor="w",
                corner_radius=8,
                fg_color="transparent",
                hover_color=COLORS["muted"],
                text_color=COLORS["text"],
                font=FONTS["body_bold"],
                command=lambda item=key: self.on_select(item),
            )
            button.grid(row=row, column=0, sticky="ew", pady=2)
            self.buttons[key] = button

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 18))
        footer.grid_columnconfigure(0, weight=1)

        self.status_pill = StatusPill(footer, "Инициализация", "warning", width=205)
        self.status_pill.grid(row=0, column=0, sticky="w", pady=(0, 10))

        profile = ctk.CTkFrame(
            footer,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
        )
        profile.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        profile.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            profile,
            text="Локальный пользователь",
            anchor="w",
            text_color=COLORS["text"],
            font=FONTS["body_bold"],
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        ctk.CTkLabel(
            profile,
            text="Голосовой блок",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["small"],
        ).grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))

        controls = ctk.CTkFrame(profile, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        for col in range(3):
            controls.grid_columnconfigure(col, weight=1)

        self.mic_button = self._voice_button(controls, "🎙", self.on_toggle_listening)
        self.mic_button.grid(row=0, column=0, sticky="ew", padx=2)
        self.tts_button = self._voice_button(controls, "🎧", self.on_toggle_tts)
        self.tts_button.grid(row=0, column=1, sticky="ew", padx=2)
        self.bundle_button = self._voice_button(controls, "🎙🎧", self.on_toggle_bundle)
        self.bundle_button.grid(row=0, column=2, sticky="ew", padx=2)

        self.voice_label = ctk.CTkLabel(
            profile,
            text="Микрофон выкл · озвучка выкл",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["small"],
        )
        self.voice_label.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 10))

        ctk.CTkLabel(
            footer,
            text=APP_VERSION,
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["small"],
        ).grid(row=2, column=0, sticky="ew", pady=(2, 0))

    def set_active(self, key: str) -> None:
        for item, button in self.buttons.items():
            active = item == key
            button.configure(
                fg_color=COLORS["surface"] if active else "transparent",
                hover_color=COLORS["surface"] if active else COLORS["muted"],
                text_color=COLORS["accent"] if active else COLORS["text"],
            )

    def set_status(self, text: str, tone: str = "muted") -> None:
        self.status_pill.set(text, tone)

    def _voice_button(self, parent, text: str, command: Callable[[], None]) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=44,
            height=34,
            corner_radius=8,
            fg_color=COLORS["muted"],
            hover_color=COLORS["border"],
            text_color=COLORS["text"],
            font=("Segoe UI", 15, "bold"),
        )

    def set_voice_state(self, listening: bool, tts_enabled: bool) -> None:
        active = COLORS["accent"]
        inactive = COLORS["muted"]
        active_hover = COLORS["accent_hover"]
        inactive_hover = COLORS["border"]
        self.mic_button.configure(
            fg_color=active if listening else inactive,
            hover_color=active_hover if listening else inactive_hover,
            text_color="#FFFFFF" if listening else COLORS["text"],
        )
        self.tts_button.configure(
            fg_color=active if tts_enabled else inactive,
            hover_color=active_hover if tts_enabled else inactive_hover,
            text_color="#FFFFFF" if tts_enabled else COLORS["text"],
        )
        both = listening and tts_enabled
        self.bundle_button.configure(
            fg_color=active if both else inactive,
            hover_color=active_hover if both else inactive_hover,
            text_color="#FFFFFF" if both else COLORS["text"],
        )
        mic_text = "микрофон вкл" if listening else "микрофон выкл"
        tts_text = "озвучка вкл" if tts_enabled else "озвучка выкл"
        self.voice_label.configure(text=f"{mic_text} · {tts_text}")
