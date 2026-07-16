"""Audio device and microphone testing page."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from ..components import StatusPill, action_button, card
from ..theme import COLORS, FONTS


class AudioPage(ctk.CTkFrame):
    def __init__(self, parent, adapter, app) -> None:
        super().__init__(parent, fg_color="transparent")
        self.adapter = adapter
        self.app = app
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.testing_microphone = False
        self.devices_loaded = False
        self.refreshing_devices = False
        self.meter_bars: list[ctk.CTkFrame] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        panel = card(self)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(panel, text="Аудионастройки", anchor="w", text_color=COLORS["text"], font=FONTS["title"]).grid(
            row=0,
            column=0,
            sticky="ew",
            padx=18,
            pady=(18, 4),
        )
        ctk.CTkLabel(
            panel,
            text="Выбор устройств, проверка микрофона и тест вывода.",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["body"],
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 16))

        form = ctk.CTkFrame(panel, fg_color="transparent")
        form.grid(row=2, column=0, sticky="ew", padx=18)
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="Микрофон", anchor="w", font=FONTS["body_bold"], text_color=COLORS["text"]).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 16),
            pady=8,
        )
        self.input_menu = ctk.CTkOptionMenu(
            form,
            variable=self.input_var,
            values=[],
            fg_color=COLORS["input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["muted"],
            text_color=COLORS["text"],
            height=36,
            corner_radius=8,
        )
        self.input_menu.grid(row=0, column=1, sticky="ew", pady=8)

        ctk.CTkLabel(form, text="Вывод", anchor="w", font=FONTS["body_bold"], text_color=COLORS["text"]).grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 16),
            pady=8,
        )
        self.output_menu = ctk.CTkOptionMenu(
            form,
            variable=self.output_var,
            values=[],
            fg_color=COLORS["input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["muted"],
            text_color=COLORS["text"],
            height=36,
            corner_radius=8,
        )
        self.output_menu.grid(row=1, column=1, sticky="ew", pady=8)

        meter_card = ctk.CTkFrame(panel, fg_color=COLORS["surface_alt"], corner_radius=8)
        meter_card.grid(row=3, column=0, sticky="ew", padx=18, pady=(18, 8))
        meter_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            meter_card,
            text="Live-индикатор уровня микрофона",
            anchor="w",
            text_color=COLORS["text"],
            font=FONTS["body_bold"],
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 2))
        ctk.CTkLabel(
            meter_card,
            text="Говорите в микрофон: сегменты показывают текущий уровень сигнала.",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["small"],
        ).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))

        meter = ctk.CTkFrame(meter_card, fg_color=COLORS["muted"], corner_radius=8)
        meter.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 14))
        for index in range(24):
            meter.grid_columnconfigure(index, weight=1)
            bar = ctk.CTkFrame(meter, fg_color=COLORS["border"], corner_radius=5, height=32)
            bar.grid(row=0, column=index, sticky="ew", padx=3, pady=10)
            self.meter_bars.append(bar)

        self.status = StatusPill(panel, "Выберите устройства и проверьте звук.", "info")
        self.status.grid(row=4, column=0, sticky="w", padx=18, pady=(6, 10))

        buttons = ctk.CTkFrame(panel, fg_color="transparent")
        buttons.grid(row=5, column=0, sticky="ew", padx=18, pady=(4, 18))
        for index in range(4):
            buttons.grid_columnconfigure(index, weight=1)

        actions = [
            ("Обновить список", self.refresh_devices, "ghost"),
            ("Тест микрофона", self.start_microphone_test, "primary"),
            ("Стоп теста", self.stop_microphone_test, "ghost"),
            ("Тест сигнала", self.test_signal, "ghost"),
            ("Тест озвучки", self.test_speech, "ghost"),
            ("Применить", self.apply_settings, "primary"),
            ("Закрыть", lambda: self.app.navigate("chat"), "ghost"),
        ]
        for index, (text, command, tone) in enumerate(actions):
            action_button(buttons, text, command, tone=tone, width=145).grid(
                row=index // 4,
                column=index % 4,
                sticky="ew",
                padx=4,
                pady=4,
            )

        self.input_menu.configure(values=["Нажмите «Обновить список»"])
        self.output_menu.configure(values=["Нажмите «Обновить список»"])
        self.input_var.set("Нажмите «Обновить список»")
        self.output_var.set("Нажмите «Обновить список»")

    def on_show(self) -> None:
        if not self.devices_loaded and not self.refreshing_devices:
            self.refresh_devices(log=False)

    def refresh_devices(self, log: bool = True) -> None:
        if self.refreshing_devices:
            return
        self.refreshing_devices = True
        self.status.set("Обновляю список устройств...", "warning")

        def worker() -> tuple[list[str], list[str]]:
            return self.adapter.refresh_audio_devices()

        def success(payload: tuple[list[str], list[str]]) -> None:
            input_values, output_values = payload
            self.input_menu.configure(values=input_values)
            self.output_menu.configure(values=output_values)
            self.input_var.set(self.adapter.current_audio_label("input"))
            self.output_var.set(self.adapter.current_audio_label("output"))
            self.status.set("Список устройств обновлен.", "success")
            self.devices_loaded = True
            self.refreshing_devices = False
            if log:
                self.adapter.log_action("Список аудиоустройств обновлен.")

        def failure(error: Exception) -> None:
            self.refreshing_devices = False
            self.status.set("Не удалось получить устройства.", "danger")
            self.app.show_notice(f"Не удалось получить список устройств: {error}", "danger")

        self.app.run_async(worker, on_success=success, on_error=failure)

    def selected_input_index(self) -> int | None:
        return self.adapter.selected_audio_index("input", self.input_var.get())

    def selected_output_index(self) -> int | None:
        return self.adapter.selected_audio_index("output", self.output_var.get())

    def start_microphone_test(self) -> None:
        self.adapter.log_action("Запуск теста микрофона.")

        def worker() -> str:
            self.adapter.start_microphone_test(self.selected_input_index())
            return "Тест микрофона запущен."

        self.app.run_async(
            worker,
            on_success=lambda message: self._microphone_started(message),
            on_error=lambda error: self.app.show_notice(f"Не удалось запустить тест микрофона: {error}", "danger"),
        )

    def _microphone_started(self, message: str) -> None:
        self.status.set(message, "success")
        self.testing_microphone = True
        self._poll_microphone()

    def _poll_microphone(self) -> None:
        if not self.testing_microphone:
            return
        level, error = self.adapter.microphone_level()
        self._render_meter(level)
        if error:
            self.status.set(f"Ошибка теста: {error}", "danger")
        self.after(60, self._poll_microphone)

    def _render_meter(self, level: float) -> None:
        active = int(round(max(0.0, min(1.0, level)) * len(self.meter_bars)))
        for index, bar in enumerate(self.meter_bars):
            if index >= active:
                color = COLORS["border"]
            elif index < 16:
                color = COLORS["success"]
            elif index < 21:
                color = COLORS["warning"]
            else:
                color = COLORS["danger"]
            bar.configure(fg_color=color)

    def stop_microphone_test(self) -> None:
        self.testing_microphone = False
        self.adapter.stop_microphone_test()
        self._render_meter(0.0)
        self.status.set("Тест микрофона остановлен.", "muted")
        self.adapter.log_action("Тест микрофона остановлен.")

    def test_signal(self) -> None:
        self.adapter.log_action("Запуск тестового сигнала.")
        self.app.run_async(
            lambda: self.adapter.play_output_signal(self.selected_output_index()),
            on_success=lambda label: self.status.set(f"Тестовый сигнал отправлен на {label}.", "success"),
            on_error=lambda error: self.app.show_notice(f"Не удалось воспроизвести тестовый сигнал: {error}", "danger"),
        )

    def test_speech(self) -> None:
        self.status.set("Запускаю тест озвучки...", "info")
        self.adapter.log_action("Запуск теста озвучки.")
        self.app.run_async(
            lambda: self.adapter.test_output_speech(self.selected_output_index()),
            on_success=lambda _result: self.status.set("Тест озвучки завершен.", "success"),
            on_error=lambda error: self.app.show_notice(f"Не удалось выполнить тест озвучки: {error}", "danger"),
        )

    def apply_settings(self) -> None:
        self.adapter.log_action("Применяю аудионастройки.")

        def worker() -> str:
            return self.adapter.apply_audio_settings(
                self.selected_input_index(),
                self.selected_output_index(),
                activation_mode=self.adapter.config.activation_mode,
                wake_words=self.adapter.config.wake_words,
                wake_window_sec=self.adapter.config.wake_window_sec,
                voice_activation_threshold=self.adapter.config.voice_activation_threshold,
            )

        self.app.run_async(
            worker,
            on_success=lambda message: self.status.set(f"Настройки сохранены. {message}", "success"),
            on_error=lambda error: self.app.show_notice(f"Не удалось применить аудионастройки: {error}", "danger"),
        )
