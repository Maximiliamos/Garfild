"""General application settings page."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

import garfield_best as core
from garfield_config import clamp_int
from garfield_secrets import PROVIDERS

from ..components import ConfirmDialog, action_button, card, labeled_input
from ..theme import COLORS, FONTS


class SettingsPage(ctk.CTkFrame):
    def __init__(self, parent, adapter, app) -> None:
        super().__init__(parent, fg_color="transparent")
        self.adapter = adapter
        self.app = app

        self.vars: dict[str, tk.Variable] = {
            "assistant_name": tk.StringVar(),
            "input_mode": tk.StringVar(),
            "ui_mode": tk.StringVar(),
            "auto_listen": tk.BooleanVar(),
            "tts_enabled": tk.BooleanVar(),
            "enable_desktop_commands": tk.BooleanVar(),
            "allow_power_commands": tk.BooleanVar(),
            "screen_hints_enabled": tk.BooleanVar(),
            "command_confirmation_timeout_sec": tk.StringVar(),
            "confirm_phrases": tk.StringVar(),
            "cancel_phrases": tk.StringVar(),
            "tts_voice": tk.StringVar(),
            "vosk_model_path": tk.StringVar(),
            "piper_model_path": tk.StringVar(),
            "piper_config_path": tk.StringVar(),
            "llm_provider": tk.StringVar(),
            "llm_api_url": tk.StringVar(),
            "allow_custom_llm_endpoint": tk.BooleanVar(),
            "llm_model": tk.StringVar(),
            "nvidia_api_key": tk.StringVar(),
            "openai_api_key": tk.StringVar(),
            "gemini_api_key": tk.StringVar(),
            "groq_api_key": tk.StringVar(),
            "xai_api_key": tk.StringVar(),
            "remember_turns": tk.StringVar(),
            "max_cached_answers": tk.StringVar(),
            "skills_path": tk.StringVar(),
        }
        self.model_menu: ctk.CTkOptionMenu | None = None
        self.api_url_entry: ctk.CTkEntry | None = None
        self.secret_status_labels: dict[str, ctk.CTkLabel] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        panel = card(self)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(panel, text="Настройки", anchor="w", text_color=COLORS["text"], font=FONTS["title"]).grid(
            row=0,
            column=0,
            sticky="ew",
            padx=18,
            pady=(18, 4),
        )
        ctk.CTkLabel(
            panel,
            text="Общие параметры ассистента, моделей, API и локальных путей.",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["body"],
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))

        self.form = ctk.CTkScrollableFrame(panel, fg_color=COLORS["surface"])
        self.form.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 12))
        self.form.grid_columnconfigure(1, weight=1)

        row = 0
        row = self._section("Профиль и режимы", row)
        labeled_input(self.form, "Имя ассистента", row, self.vars["assistant_name"]); row += 1
        self._option("Режим ввода", row, self.vars["input_mode"], ["auto", "voice", "keyboard"]); row += 1
        self._option("Режим интерфейса", row, self.vars["ui_mode"], ["gui", "console", "auto"]); row += 1
        self._switch("Автопрослушивание при запуске", row, self.vars["auto_listen"]); row += 1
        self._switch("Озвучка ответов", row, self.vars["tts_enabled"]); row += 1
        self._switch("Desktop-команды", row, self.vars["enable_desktop_commands"]); row += 1
        self._switch("Силовые команды", row, self.vars["allow_power_commands"]); row += 1
        self._switch("Экранные подсказки", row, self.vars["screen_hints_enabled"]); row += 1

        row = self._section("Подтверждение команд", row)
        labeled_input(self.form, "Автоотмена, сек", row, self.vars["command_confirmation_timeout_sec"]); row += 1
        labeled_input(self.form, "Фразы подтверждения", row, self.vars["confirm_phrases"]); row += 1
        labeled_input(self.form, "Фразы отмены", row, self.vars["cancel_phrases"]); row += 1

        row = self._section("Модели и API", row)
        labeled_input(self.form, "Vosk model path", row, self.vars["vosk_model_path"]); row += 1
        labeled_input(self.form, "Голос Edge TTS", row, self.vars["tts_voice"]); row += 1
        labeled_input(self.form, "Piper model path", row, self.vars["piper_model_path"]); row += 1
        labeled_input(self.form, "Piper config path", row, self.vars["piper_config_path"]); row += 1
        self._option(
            "ИИ провайдер",
            row,
            self.vars["llm_provider"],
            core.llm_provider_keys(),
            command=self._on_provider_change,
        ); row += 1
        self.model_menu = self._option("Модель ответа", row, self.vars["llm_model"], core.llm_model_ids("nvidia")); row += 1
        self.api_url_entry = labeled_input(
            self.form,
            "API URL",
            row,
            self.vars["llm_api_url"],
        )
        row += 1
        self._switch(
            "Разрешить пользовательский endpoint",
            row,
            self.vars["allow_custom_llm_endpoint"],
            command=self._on_custom_endpoint_toggle,
        )
        row += 1
        ctk.CTkLabel(
            self.form,
            text=(
                "Внимание: при пользовательском endpoint API-ключ будет "
                "отправлен на выбранный сервер."
            ),
            anchor="w",
            justify="left",
            wraplength=700,
            text_color=COLORS["warning"],
            font=FONTS["small"],
        ).grid(row=row, column=1, sticky="ew", pady=(0, 8))
        row += 1
        provider_labels = {
            "nvidia": "NVIDIA API key",
            "openai": "OpenAI API key",
            "gemini": "Gemini API key",
            "groq": "Groq Cloud API key",
            "xai": "xAI Grok API key",
        }
        for provider in PROVIDERS:
            self._secret_input(provider_labels[provider], provider, row)
            row += 1

        row = self._section("Память и навыки", row)
        labeled_input(self.form, "Количество ходов памяти", row, self.vars["remember_turns"]); row += 1
        labeled_input(self.form, "Максимум кэшированных ответов", row, self.vars["max_cached_answers"]); row += 1
        labeled_input(self.form, "Путь к файлу навыков", row, self.vars["skills_path"]); row += 1

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 18))
        actions.grid_columnconfigure(0, weight=1)
        action_button(actions, "Сбросить к значениям по умолчанию", self.reset_defaults, tone="ghost", width=230).grid(row=0, column=1, padx=(0, 10))
        action_button(actions, "Проверить подключение", self.check_connection, tone="ghost", width=180).grid(row=0, column=2, padx=(0, 10))
        action_button(actions, "Сохранить настройки", self.save_settings, width=180).grid(row=0, column=3)

        self.load_from_config()

    def _section(self, title: str, row: int) -> int:
        ctk.CTkLabel(self.form, text=title, anchor="w", text_color=COLORS["accent"], font=FONTS["section"]).grid(
            row=row,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(18 if row else 4, 6),
        )
        return row + 1

    def _option(self, label: str, row: int, variable, values: list[str], command=None):
        ctk.CTkLabel(self.form, text=label, anchor="w", text_color=COLORS["text"], font=FONTS["body_bold"]).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 16),
            pady=8,
        )
        menu = ctk.CTkOptionMenu(
            self.form,
            values=values,
            variable=variable,
            command=command,
            fg_color=COLORS["input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            text_color=COLORS["text"],
            height=36,
            corner_radius=8,
        )
        menu.grid(row=row, column=1, sticky="ew", pady=8)
        return menu

    def _switch(
        self,
        label: str,
        row: int,
        variable,
        command=None,
    ) -> None:
        ctk.CTkLabel(self.form, text=label, anchor="w", text_color=COLORS["text"], font=FONTS["body_bold"]).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 16),
            pady=8,
        )
        ctk.CTkSwitch(
            self.form,
            text="",
            variable=variable,
            progress_color=COLORS["accent"],
            command=command,
        ).grid(
            row=row,
            column=1,
            sticky="w",
            pady=8,
        )

    def _secret_input(self, label: str, provider: str, row: int) -> None:
        ctk.CTkLabel(
            self.form,
            text=label,
            anchor="w",
            text_color=COLORS["text"],
            font=FONTS["body_bold"],
        ).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=8)
        controls = ctk.CTkFrame(self.form, fg_color="transparent")
        controls.grid(row=row, column=1, sticky="ew", pady=8)
        controls.grid_columnconfigure(0, weight=1)
        entry = ctk.CTkEntry(
            controls,
            textvariable=self.vars[f"{provider}_api_key"],
            show="*",
            fg_color=COLORS["input"],
            text_color=COLORS["text"],
            height=36,
        )
        entry.grid(row=0, column=0, sticky="ew")
        status = ctk.CTkLabel(
            controls,
            text="",
            text_color=COLORS["text_secondary"],
            width=105,
        )
        status.grid(row=0, column=1, padx=8)
        self.secret_status_labels[provider] = status
        action_button(
            controls,
            "Сохранить",
            lambda p=provider: self.save_secret(p),
            width=90,
        ).grid(row=0, column=2, padx=(0, 6))
        action_button(
            controls,
            "Удалить",
            lambda p=provider: self.delete_secret(p),
            tone="danger",
            width=80,
        ).grid(row=0, column=3)

    def load_from_config(self) -> None:
        cfg = self.adapter.config
        values = {
            "assistant_name": cfg.assistant_name,
            "input_mode": cfg.input_mode,
            "ui_mode": cfg.ui_mode,
            "auto_listen": cfg.auto_listen,
            "tts_enabled": cfg.tts_enabled,
            "enable_desktop_commands": cfg.enable_desktop_commands,
            "allow_power_commands": cfg.allow_power_commands,
            "screen_hints_enabled": cfg.screen_hints_enabled,
            "command_confirmation_timeout_sec": str(cfg.command_confirmation_timeout_sec),
            "confirm_phrases": ", ".join(cfg.confirm_phrases),
            "cancel_phrases": ", ".join(cfg.cancel_phrases),
            "tts_voice": cfg.tts_voice,
            "vosk_model_path": cfg.vosk_model_path,
            "piper_model_path": cfg.piper_model_path,
            "piper_config_path": cfg.piper_config_path,
            "llm_provider": core.normalize_llm_provider(getattr(cfg, "llm_provider", "nvidia")),
            "llm_api_url": cfg.llm_api_url,
            "allow_custom_llm_endpoint": cfg.allow_custom_llm_endpoint,
            "llm_model": cfg.llm_model,
            "nvidia_api_key": "",
            "openai_api_key": "",
            "gemini_api_key": "",
            "groq_api_key": "",
            "xai_api_key": "",
            "remember_turns": str(cfg.remember_turns),
            "max_cached_answers": str(cfg.max_cached_answers),
            "skills_path": cfg.skills_path,
        }
        for key, value in values.items():
            self.vars[key].set(value)
        self._refresh_secret_statuses()
        self._refresh_model_options()
        self._refresh_endpoint_state()

    def _on_provider_change(self, _value: str | None = None) -> None:
        provider = core.normalize_llm_provider(self.vars["llm_provider"].get())
        self.vars["llm_api_url"].set(core.default_llm_api_url(provider))
        self._refresh_model_options()

    def _on_custom_endpoint_toggle(self) -> None:
        if not bool(self.vars["allow_custom_llm_endpoint"].get()):
            provider = core.normalize_llm_provider(
                self.vars["llm_provider"].get()
            )
            self.vars["llm_api_url"].set(
                core.default_llm_api_url(provider)
            )
        self._refresh_endpoint_state()

    def _refresh_endpoint_state(self) -> None:
        if self.api_url_entry is None:
            return
        self.api_url_entry.configure(
            state=(
                "normal"
                if bool(self.vars["allow_custom_llm_endpoint"].get())
                else "disabled"
            )
        )

    def _refresh_model_options(self) -> None:
        provider = core.normalize_llm_provider(self.vars["llm_provider"].get())
        models = core.llm_model_ids(provider)
        if self.model_menu is not None:
            self.model_menu.configure(values=models)
        if self.vars["llm_model"].get() not in models:
            self.vars["llm_model"].set(core.default_llm_model(provider))

    def _collect(self) -> dict[str, object]:
        secret_fields = {f"{provider}_api_key" for provider in PROVIDERS}
        values = {
            key: variable.get()
            for key, variable in self.vars.items()
            if key not in secret_fields
        }
        values["remember_turns"] = clamp_int(
            values["remember_turns"],
            1,
            100,
            "Количество ходов памяти",
        )
        values["max_cached_answers"] = clamp_int(
            values["max_cached_answers"],
            1,
            10_000,
            "Максимум кэшированных ответов",
        )
        values["command_confirmation_timeout_sec"] = clamp_int(
            values["command_confirmation_timeout_sec"],
            5,
            120,
            "Автоотмена команды",
        )
        return values

    def _refresh_secret_statuses(self) -> None:
        statuses = self.adapter.secret_statuses()
        for provider, label in self.secret_status_labels.items():
            label.configure(
                text="[сохранён]" if statuses.get(provider) else "[не задан]",
                text_color=(
                    COLORS["success"]
                    if statuses.get(provider)
                    else COLORS["text_secondary"]
                ),
            )

    def save_secret(self, provider: str) -> None:
        value = str(self.vars[f"{provider}_api_key"].get()).strip()
        if not value:
            self.app.show_notice("Введите новый API-ключ.", "warning")
            return
        try:
            message = self.adapter.save_secret(provider, value)
            self.vars[f"{provider}_api_key"].set("")
            self._refresh_secret_statuses()
            self.app.show_notice(message, "success")
        except Exception as error:
            self.app.show_notice(f"Не удалось сохранить API-ключ: {error}", "danger")

    def delete_secret(self, provider: str) -> None:
        def delete() -> None:
            try:
                message = self.adapter.delete_secret(provider)
                self.vars[f"{provider}_api_key"].set("")
                self._refresh_secret_statuses()
                self.app.show_notice(message, "warning")
            except Exception as error:
                self.app.show_notice(f"Не удалось удалить API-ключ: {error}", "danger")

        ConfirmDialog(
            self,
            "Удалить API-ключ",
            f"Удалить сохранённый ключ {provider} из безопасного хранилища?",
            delete,
            confirm_text="Удалить",
            danger=True,
        )

    def save_settings(self) -> None:
        try:
            values = self._collect()
            message = self.adapter.apply_general_settings(values)
            self.app.show_notice(message, "success")
            self.adapter.log_action("Общие настройки сохранены через интерфейс.")
        except Exception as error:
            self.app.show_notice(f"Не удалось сохранить настройки: {error}", "danger")

    def check_connection(self) -> None:
        self.adapter.log_action("Проверка подключения к ИИ-провайдеру.")
        self.app.run_async(
            self.adapter.check_llm_connection,
            on_success=lambda message: self.app.show_notice(message, "success" if "отвечает" in message else "warning"),
            on_error=lambda error: self.app.show_notice(f"Ошибка проверки ИИ-провайдера: {error}", "danger"),
        )

    def reset_defaults(self) -> None:
        def reset() -> None:
            try:
                message = self.adapter.reset_config_defaults()
                self.load_from_config()
                self.app.show_notice(message, "warning")
                self.adapter.log_action("Настройки сброшены к значениям по умолчанию.")
            except Exception as error:
                self.app.show_notice(f"Не удалось сбросить настройки: {error}", "danger")

        ConfirmDialog(
            self,
            "Сбросить настройки",
            "Вернуть конфиг к значениям по умолчанию? Часть режимов полностью применится после перезапуска.",
            reset,
            confirm_text="Сбросить",
            danger=True,
        )
