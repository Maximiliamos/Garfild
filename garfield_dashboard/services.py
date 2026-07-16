"""Adapters that keep the modern UI decoupled from the existing assistant core."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import garfield_best as core
from garfield_io import atomic_write_text


@dataclass
class DashboardPaths:
    base_dir: Path
    config_path: Path
    log_path: Path
    session_log_path: Path


@dataclass
class DiagnosticItem:
    title: str
    value: str
    tone: str = "muted"


@dataclass
class SkillRecord:
    skill_id: str = ""
    phrases: list[str] = field(default_factory=list)
    action_id: str = "assistant.say"
    target: str = ""
    response: str = ""

    @classmethod
    def from_skill(cls, skill: Any) -> "SkillRecord":
        action_id = getattr(skill, "action_id", "assistant.say")
        arguments = dict(getattr(skill, "arguments", {}))
        target_key = {
            "web.open": "url",
            "web.search": "query",
            "application.open": "app_id",
            "project_file.open": "path",
        }.get(action_id, "")
        return cls(
            skill_id=getattr(skill, "skill_id", ""),
            phrases=list(getattr(skill, "phrases", [])),
            action_id=action_id,
            target=str(arguments.get(target_key, "")),
            response=getattr(skill, "response", ""),
        )

    def to_json(self) -> dict[str, Any]:
        argument_key = {
            "web.open": "url",
            "web.search": "query",
            "application.open": "app_id",
            "project_file.open": "path",
        }.get(self.action_id)
        payload: dict[str, Any] = {
            "id": self.skill_id.strip(),
            "phrases": [item.strip() for item in self.phrases if item.strip()],
            "action_id": self.action_id.strip(),
            "arguments": (
                {argument_key: self.target.strip()} if argument_key else {}
            ),
        }
        if self.response.strip():
            payload["response"] = self.response.strip()
        return payload


class RuntimeAdapter:
    """Thin bridge between CustomTkinter pages and FlagshipRuntime."""

    def __init__(
        self,
        runtime: Any,
        *,
        save_config: Callable[[Any], None],
        paths: DashboardPaths,
    ) -> None:
        self.runtime = runtime
        self.save_config_callback = save_config
        self.paths = paths
        self.input_options: dict[str, int | None] = {}
        self.output_options: dict[str, int | None] = {}
        self._mic_monitor: core.AudioLevelMonitor | None = None
        self._mic_lock = threading.Lock()
        self._listening_toggle_lock = threading.Lock()

    @property
    def config(self) -> Any:
        return self.runtime.config

    def start(self) -> None:
        self.runtime.start()

    def stop(self) -> None:
        self.stop_microphone_test()
        self.runtime.stop()

    def drain_events(self) -> list[Any]:
        return self.runtime.drain_events()

    def log_action(self, message: str) -> None:
        self.runtime.emit("status", message)

    def submit_command(self, text: str, source: str = "gui") -> None:
        self.runtime.submit_text(text, source=source)

    def set_listening(self, enabled: bool) -> None:
        with self._listening_toggle_lock:
            self.runtime.set_listening(enabled)

    def save_current_config(self) -> None:
        self.save_config_callback(self.config)

    def save_session_history(self) -> Path:
        return self.runtime._save_session_history()

    def clear_dialog_memory(self) -> None:
        self.runtime.assistant.history.turns.clear()
        self.runtime.assistant.last_answer = ""
        self.runtime.assistant.last_user_command = ""
        self.runtime.assistant.previous_user_command = ""

    def clear_answer_cache(self) -> None:
        if hasattr(self.runtime.assistant, "answer_cache"):
            self.runtime.assistant.answer_cache.clear()

    def clear_session_history(self) -> None:
        self.runtime.session_lines.clear()

    def open_project_folder(self) -> str:
        os.startfile(str(self.paths.base_dir))
        return "Открываю папку проекта."

    def open_log_file(self) -> str:
        if not self.paths.log_path.exists():
            raise FileNotFoundError(f"Лог еще не создан: {self.paths.log_path}")
        os.startfile(str(self.paths.log_path))
        return "Открываю лог приложения."

    def diagnostics(self) -> list[DiagnosticItem]:
        cfg = self.config
        assistant = self.runtime.assistant
        llm_available = bool(assistant.llm_client and assistant.llm_client.is_available())
        vosk_ready = self.runtime.voice_recognizer is not None or Path(cfg.vosk_model_path).exists()
        piper_ready = Path(cfg.piper_model_path).exists() and Path(cfg.piper_config_path).exists()
        cache_size = len(getattr(assistant, "answer_cache", {}))
        dialog_size = len(assistant.history.turns)
        skills_error = getattr(assistant.skills, "load_error", None)
        skills_count = assistant.skills.count()
        mic_label = self._safe_describe_audio("input", cfg.input_device_index)
        output_label = self._safe_describe_audio("output", cfg.output_device_index)

        return [
            DiagnosticItem("Vosk-модель", "готова" if vosk_ready else "не найдена", "success" if vosk_ready else "danger"),
            DiagnosticItem("Piper TTS", "готов" if piper_ready else "недоступен", "success" if piper_ready else "warning"),
            DiagnosticItem(
                "ИИ-провайдер",
                f"{core.describe_llm_provider(cfg.llm_provider)}: {'доступен' if llm_available else 'недоступен'}",
                "success" if llm_available else "warning",
            ),
            DiagnosticItem("GUI", "CustomTkinter dashboard", "success"),
            DiagnosticItem("Режим ввода", str(self.runtime.input_mode), "info"),
            DiagnosticItem("Прослушивание", "включено" if self.runtime.listening_enabled else "выключено", "success" if self.runtime.listening_enabled else "muted"),
            DiagnosticItem("TTS", "включена" if self.runtime.tts.enabled else "выключена", "success" if self.runtime.tts.enabled else "muted"),
            DiagnosticItem("Режим активации", "по ключевой фразе" if cfg.activation_mode == "wake_word" else "непрерывный", "info"),
            DiagnosticItem("Ключевая фраза", ", ".join(cfg.wake_words), "info"),
            DiagnosticItem("Шумовой порог", str(int(cfg.voice_activation_threshold * 1000)), "info"),
            DiagnosticItem("Уверенность речи", f"{int(cfg.recognition_confidence_threshold * 100)}%", "info"),
            DiagnosticItem("Уверенность префикса", f"{int(cfg.wake_word_confidence_threshold * 100)}%", "info"),
            DiagnosticItem("Экранные подсказки", "включены" if cfg.screen_hints_enabled else "выключены", "success" if cfg.screen_hints_enabled else "muted"),
            DiagnosticItem("Количество навыков", f"{skills_count}" if not skills_error else f"ошибка: {skills_error}", "success" if not skills_error else "danger"),
            DiagnosticItem("Микрофон", mic_label, "info" if "ошибка" not in mic_label else "warning"),
            DiagnosticItem("Вывод", output_label, "info" if "ошибка" not in output_label else "warning"),
            DiagnosticItem("Память диалога", str(dialog_size), "info"),
            DiagnosticItem("Размер кэша ответов", str(cache_size), "info"),
            DiagnosticItem("Силовые команды", "включены" if cfg.allow_power_commands else "отключены", "warning" if cfg.allow_power_commands else "muted"),
        ]

    def _safe_describe_audio(self, kind: str, preferred_index: int | None) -> str:
        try:
            return core.describe_audio_device(kind, preferred_index)
        except Exception as error:
            return f"ошибка аудио: {error}"

    def refresh_audio_devices(self) -> tuple[list[str], list[str]]:
        input_devices = core.get_audio_devices("input")
        output_devices = core.get_audio_devices("output")

        self.input_options = {f"Авто: {core.describe_audio_device('input', None)}": None}
        for device in input_devices:
            self.input_options[core.format_audio_device_label(device, "input")] = device.index

        self.output_options = {f"Авто: {core.describe_audio_device('output', None)}": None}
        for device in output_devices:
            self.output_options[core.format_audio_device_label(device, "output")] = device.index

        return list(self.input_options.keys()), list(self.output_options.keys())

    def current_audio_label(self, kind: str) -> str:
        options = self.input_options if kind == "input" else self.output_options
        current_index = self.config.input_device_index if kind == "input" else self.config.output_device_index
        for label, index in options.items():
            if index == current_index:
                return label
        return next(iter(options.keys()), "Авто")

    def selected_audio_index(self, kind: str, label: str) -> int | None:
        options = self.input_options if kind == "input" else self.output_options
        return options.get(label)

    def apply_audio_settings(
        self,
        input_index: int | None,
        output_index: int | None,
        *,
        activation_mode: str | None = None,
        wake_words: list[str] | None = None,
        wake_window_sec: int | None = None,
        voice_activation_threshold: float | None = None,
        recognition_confidence_threshold: float | None = None,
        wake_word_confidence_threshold: float | None = None,
    ) -> str:
        summary = self.runtime.apply_audio_settings(
            input_index,
            output_index,
            activation_mode=activation_mode,
            wake_words=wake_words,
            wake_window_sec=wake_window_sec,
            voice_activation_threshold=voice_activation_threshold,
            recognition_confidence_threshold=recognition_confidence_threshold,
            wake_word_confidence_threshold=wake_word_confidence_threshold,
        )
        self.save_current_config()
        return summary

    def start_microphone_test(self, input_index: int | None) -> None:
        self.stop_microphone_test()
        with self._mic_lock:
            self._mic_monitor = core.AudioLevelMonitor(input_index)
            self._mic_monitor.start()

    def microphone_level(self) -> tuple[float, str | None]:
        with self._mic_lock:
            if not self._mic_monitor:
                return 0.0, None
            return self._mic_monitor.get_level(), self._mic_monitor.error

    def stop_microphone_test(self) -> None:
        with self._mic_lock:
            if self._mic_monitor:
                self._mic_monitor.stop()
                self._mic_monitor = None

    def play_output_signal(self, output_index: int | None) -> str:
        return core.play_output_test_tone(output_index)

    def test_output_speech(self, output_index: int | None) -> None:
        speaker = core.Speaker(
            self.config.assistant_name,
            output_index,
            self.config.tts_voice,
            self.config.piper_model_path,
            self.config.piper_config_path,
        )
        speaker.speak("Проверка звука Гарфилда. Если вы меня слышите, значит вывод настроен правильно.")

    def skill_records(self) -> list[SkillRecord]:
        return [SkillRecord.from_skill(skill) for skill in self.runtime.assistant.skills.skills]

    def reload_skills(self) -> str:
        return self.runtime.reload_skills()

    def open_skills_file(self) -> str:
        return self.runtime.open_skills_file()

    def save_skill_records(self, records: list[SkillRecord]) -> str:
        path = Path(self.config.skills_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "skills": [record.to_json() for record in records],
        }
        atomic_write_text(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
        count, error = self.runtime.assistant.skills.reload()
        if error:
            raise RuntimeError(error)
        return f"Навыки сохранены. Активно {count}."

    def apply_general_settings(self, values: dict[str, Any]) -> str:
        cfg = self.config
        cfg.assistant_name = values["assistant_name"].strip() or "Гарфилд"
        cfg.input_mode = values["input_mode"]
        cfg.ui_mode = values["ui_mode"]
        cfg.auto_listen = bool(values["auto_listen"])
        cfg.tts_enabled = bool(values["tts_enabled"])
        cfg.enable_desktop_commands = bool(values["enable_desktop_commands"])
        cfg.allow_power_commands = bool(values["allow_power_commands"])
        cfg.screen_hints_enabled = bool(values["screen_hints_enabled"])
        cfg.command_confirmation_timeout_sec = max(5, min(int(values["command_confirmation_timeout_sec"]), 120))
        cfg.confirm_phrases = [core.normalize_text(item) for item in str(values["confirm_phrases"]).split(",") if core.normalize_text(item)]
        cfg.cancel_phrases = [core.normalize_text(item) for item in str(values["cancel_phrases"]).split(",") if core.normalize_text(item)]
        if not cfg.confirm_phrases:
            cfg.confirm_phrases = ["да", "подтверждаю"]
        if not cfg.cancel_phrases:
            cfg.cancel_phrases = ["нет", "отмена", "отмени", "не надо"]
        cfg.vosk_model_path = values["vosk_model_path"].strip()
        cfg.tts_voice = values["tts_voice"].strip() or "ru-RU-SvetlanaNeural"
        cfg.piper_model_path = values["piper_model_path"].strip()
        cfg.piper_config_path = values["piper_config_path"].strip()
        cfg.llm_provider = core.normalize_llm_provider(values["llm_provider"])
        cfg.llm_api_url = values["llm_api_url"].strip()
        cfg.llm_api_url = core.default_llm_api_url(cfg.llm_provider, cfg.llm_api_url)
        cfg.llm_model = values["llm_model"].strip() or core.default_llm_model(cfg.llm_provider)
        cfg.nvidia_api_key = values["nvidia_api_key"].strip()
        cfg.openai_api_key = values["openai_api_key"].strip()
        cfg.gemini_api_key = values["gemini_api_key"].strip()
        cfg.groq_api_key = values["groq_api_key"].strip()
        cfg.xai_api_key = values["xai_api_key"].strip()
        cfg.remember_turns = max(1, int(values["remember_turns"]))
        cfg.max_cached_answers = max(1, int(values["max_cached_answers"]))
        cfg.skills_path = values["skills_path"].strip()

        self.runtime.tts.enabled = cfg.tts_enabled
        self.runtime.tts.speaker.assistant_name = cfg.assistant_name
        self.runtime.tts.set_voice(cfg.tts_voice)
        self.runtime.tts.speaker.piper_model_path = cfg.piper_model_path
        self.runtime.tts.speaker.piper_config_path = cfg.piper_config_path
        self.runtime.assistant.history.max_turns = cfg.remember_turns
        self.runtime.assistant.desktop.allow_power_commands = cfg.allow_power_commands
        self.runtime.assistant.llm_client = core.create_llm_client(cfg)
        self.runtime.assistant.skills.path = Path(cfg.skills_path)
        self.runtime.assistant.skills.reload()
        self.save_current_config()
        return "Настройки сохранены."

    def reset_config_defaults(self) -> str:
        default_config = type(self.config)()
        current = self.config
        for key, value in asdict(default_config).items():
            setattr(current, key, value)
        self.save_current_config()
        return "Настройки сброшены. Перезапустите приложение, чтобы полностью применить режимы ввода."

    def check_llm_connection(self) -> str:
        client = self.runtime.assistant.llm_client
        if not client or not client.is_available():
            return "ИИ-провайдер недоступен: не задан ключ или отключен LLM."
        started = time.time()
        answer = client.ask(
            "Ответь одним словом: готов.",
            self.config.assistant_name,
            self.runtime.assistant.history,
            max_tokens=16,
            timeout_sec=12,
        )
        elapsed = time.time() - started
        provider = core.describe_llm_provider(self.config.llm_provider)
        return f"{provider} отвечает за {elapsed:.1f} сек. Ответ: {answer[:80] or 'пусто'}"

    def check_nvidia_connection(self) -> str:
        return self.check_llm_connection()
