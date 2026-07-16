"""Voice activation settings page."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from ..components import StatusPill, action_button, card, labeled_input
from ..theme import COLORS, FONTS


class VoicePage(ctk.CTkFrame):
    def __init__(self, parent, adapter, app) -> None:
        super().__init__(parent, fg_color="transparent")
        self.adapter = adapter
        self.app = app

        self.listen_var = tk.BooleanVar(value=False)
        self.mode_var = tk.StringVar(value="Всегда слушать")
        self.wake_words_var = tk.StringVar()
        self.wake_window_var = tk.StringVar()
        self.noise_gate_var = tk.DoubleVar()
        self.confidence_var = tk.DoubleVar()
        self.prefix_confidence_var = tk.DoubleVar()
        self.toggle_after_id: str | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        panel = card(self)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            panel,
            text="Голосовой режим",
            anchor="w",
            text_color=COLORS["text"],
            font=FONTS["title"],
        ).grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 4))
        ctk.CTkLabel(
            panel,
            text="Управление прослушиванием, ключевой фразой и фильтрацией фонового шума.",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["body"],
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 16))

        content = ctk.CTkFrame(panel, fg_color="transparent")
        content.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 12))
        content.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(content, text="Голосовое прослушивание", anchor="w", font=FONTS["body_bold"], text_color=COLORS["text"]).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 16),
            pady=10,
        )
        ctk.CTkSwitch(
            content,
            text="",
            variable=self.listen_var,
            command=self._toggle_listening,
            progress_color=COLORS["accent"],
        ).grid(row=0, column=1, sticky="w", pady=10)

        ctk.CTkLabel(content, text="Режим", anchor="w", font=FONTS["body_bold"], text_color=COLORS["text"]).grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 16),
            pady=10,
        )
        ctk.CTkSegmentedButton(
            content,
            values=["Всегда слушать", "По ключевой фразе"],
            variable=self.mode_var,
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["surface_alt"],
            unselected_hover_color=COLORS["muted"],
            text_color=COLORS["text"],
        ).grid(row=1, column=1, sticky="ew", pady=10)

        labeled_input(content, "Ключевая фраза", 2, self.wake_words_var)
        labeled_input(content, "Окно активации, сек", 3, self.wake_window_var)

        ctk.CTkLabel(content, text="Шумовой порог", anchor="w", font=FONTS["body_bold"], text_color=COLORS["text"]).grid(
            row=4,
            column=0,
            sticky="w",
            padx=(0, 16),
            pady=10,
        )
        slider_frame = ctk.CTkFrame(content, fg_color="transparent")
        slider_frame.grid(row=4, column=1, sticky="ew", pady=10)
        slider_frame.grid_columnconfigure(0, weight=1)
        self.noise_label = ctk.CTkLabel(slider_frame, text="0", text_color=COLORS["text_secondary"], font=FONTS["small"], width=38)
        self.noise_label.grid(row=0, column=1, sticky="e", padx=(12, 0))
        ctk.CTkSlider(
            slider_frame,
            from_=0,
            to=40,
            variable=self.noise_gate_var,
            command=lambda value: self.noise_label.configure(text=str(int(float(value)))),
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
        ).grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(content, text="Уверенность речи", anchor="w", font=FONTS["body_bold"], text_color=COLORS["text"]).grid(
            row=5,
            column=0,
            sticky="w",
            padx=(0, 16),
            pady=10,
        )
        confidence_frame = ctk.CTkFrame(content, fg_color="transparent")
        confidence_frame.grid(row=5, column=1, sticky="ew", pady=10)
        confidence_frame.grid_columnconfigure(0, weight=1)
        self.confidence_label = ctk.CTkLabel(confidence_frame, text="0%", text_color=COLORS["text_secondary"], font=FONTS["small"], width=42)
        self.confidence_label.grid(row=0, column=1, sticky="e", padx=(12, 0))
        ctk.CTkSlider(
            confidence_frame,
            from_=0,
            to=100,
            variable=self.confidence_var,
            command=lambda value: self.confidence_label.configure(text=f"{int(float(value))}%"),
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
        ).grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(content, text="Уверенность префикса", anchor="w", font=FONTS["body_bold"], text_color=COLORS["text"]).grid(
            row=6,
            column=0,
            sticky="w",
            padx=(0, 16),
            pady=10,
        )
        prefix_frame = ctk.CTkFrame(content, fg_color="transparent")
        prefix_frame.grid(row=6, column=1, sticky="ew", pady=10)
        prefix_frame.grid_columnconfigure(0, weight=1)
        self.prefix_confidence_label = ctk.CTkLabel(prefix_frame, text="0%", text_color=COLORS["text_secondary"], font=FONTS["small"], width=42)
        self.prefix_confidence_label.grid(row=0, column=1, sticky="e", padx=(12, 0))
        ctk.CTkSlider(
            prefix_frame,
            from_=0,
            to=100,
            variable=self.prefix_confidence_var,
            command=lambda value: self.prefix_confidence_label.configure(text=f"{int(float(value))}%"),
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
        ).grid(row=0, column=0, sticky="ew")

        self.voice_status = StatusPill(panel, "Проверяю голосовой ввод", "warning")
        self.voice_status.grid(row=3, column=0, sticky="w", padx=18, pady=(4, 18))

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 18))
        actions.grid_columnconfigure(0, weight=1)
        action_button(actions, "Сбросить", self.reset_fields, tone="ghost", width=120).grid(row=0, column=1, padx=(0, 10))
        action_button(actions, "Применить", self.apply_settings, width=130).grid(row=0, column=2)

        self.reset_fields(log=False)

    def update_state(self) -> None:
        runtime = self.adapter.runtime
        self.listen_var.set(bool(runtime.listening_enabled))
        available = runtime.voice_recognizer is not None
        self.voice_status.set(
            "Голосовой ввод доступен" if available else "Голосовой ввод недоступен",
            "success" if available else "warning",
        )

    def reset_fields(self, log: bool = True) -> None:
        cfg = self.adapter.config
        self.mode_var.set("По ключевой фразе" if cfg.activation_mode == "wake_word" else "Всегда слушать")
        self.wake_words_var.set(", ".join(cfg.wake_words))
        self.wake_window_var.set(str(cfg.wake_window_sec))
        self.noise_gate_var.set(int(cfg.voice_activation_threshold * 1000))
        self.noise_label.configure(text=str(int(cfg.voice_activation_threshold * 1000)))
        self.confidence_var.set(int(cfg.recognition_confidence_threshold * 100))
        self.confidence_label.configure(text=f"{int(cfg.recognition_confidence_threshold * 100)}%")
        self.prefix_confidence_var.set(int(cfg.wake_word_confidence_threshold * 100))
        self.prefix_confidence_label.configure(text=f"{int(cfg.wake_word_confidence_threshold * 100)}%")
        self.update_state()
        if log:
            self.adapter.log_action("Поля голосового режима обновлены из текущих настроек.")

    def _toggle_listening(self) -> None:
        enabled = bool(self.listen_var.get())
        if self.toggle_after_id:
            self.after_cancel(self.toggle_after_id)
        self.voice_status.set("Переключаю прослушивание...", "warning")
        self.toggle_after_id = self.after(250, lambda value=enabled: self._apply_listening_toggle(value))

    def _apply_listening_toggle(self, enabled: bool) -> None:
        self.toggle_after_id = None
        self.adapter.log_action("Кнопка: включить прослушивание." if enabled else "Кнопка: выключить прослушивание.")
        self.app.run_async(
            lambda: self.adapter.set_listening(enabled),
            on_success=lambda _result: (self.update_state(), self.app._update_sidebar_voice_state()),
            on_error=lambda error: self.app.show_notice(f"Не удалось переключить прослушивание: {error}", "danger"),
        )

    def apply_settings(self) -> None:
        try:
            wake_window = int(self.wake_window_var.get().strip())
            if not 3 <= wake_window <= 60:
                raise ValueError("Окно активации должно быть от 3 до 60 секунд.")
            wake_words = [item.strip() for item in self.wake_words_var.get().split(",") if item.strip()]
            activation_mode = "wake_word" if self.mode_var.get() == "По ключевой фразе" else "continuous"
            threshold = float(self.noise_gate_var.get()) / 1000.0
            confidence = float(self.confidence_var.get()) / 100.0
            prefix_confidence = float(self.prefix_confidence_var.get()) / 100.0
        except Exception as error:
            self.app.show_notice(f"Не удалось применить голосовые настройки: {error}", "danger")
            return

        self.adapter.log_action("Применяю настройки голосового режима.")

        def worker() -> str:
            return self.adapter.apply_audio_settings(
                self.adapter.config.input_device_index,
                self.adapter.config.output_device_index,
                activation_mode=activation_mode,
                wake_words=wake_words,
                wake_window_sec=wake_window,
                voice_activation_threshold=threshold,
                recognition_confidence_threshold=confidence,
                wake_word_confidence_threshold=prefix_confidence,
            )

        self.app.run_async(
            worker,
            on_success=lambda message: (self.app.show_notice(f"Голосовые настройки сохранены. {message}", "success"), self.update_state()),
            on_error=lambda error: self.app.show_notice(f"Не удалось применить голосовые настройки: {error}", "danger"),
        )
