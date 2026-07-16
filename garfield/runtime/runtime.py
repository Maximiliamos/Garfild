from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
import time
import ctypes
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk
except ImportError:
    tk = None
    messagebox = None
    scrolledtext = None
    ttk = None

import garfield_best as core
from garfield_config import clamp_int, load_json_config, resolve_config_path
from garfield_io import atomic_write_text
from garfield_privacy import (
    SecretRedactingFilter,
    looks_sensitive,
    redact_sensitive_text,
)
from garfield_secrets import PROVIDERS, SecretStore, migrate_plaintext_secrets


BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "garfield_flagship_config.json"
LOG_PATH = BASE_DIR / "garfield_flagship.log"
SESSION_LOG_PATH = BASE_DIR / "garfield_session_history.txt"


def _prefer_existing_local_path(raw_path: str, local_fallback: Path) -> str:
    """Use the bundled project file when config still points to a moved folder."""
    if not raw_path:
        return str(local_fallback)
    candidate = Path(raw_path)
    if candidate.exists():
        return str(candidate)
    if local_fallback.exists():
        return str(local_fallback)
    return raw_path


@dataclass
class FlagshipConfig:
    assistant_name: str = "Гарфилд"
    vosk_model_path: str = ""
    recognition_timeout_sec: int = 20
    llm_provider: str = "nvidia"
    llm_api_url: str = "https://integrate.api.nvidia.com/v1/chat/completions"
    llm_model: str = "meta/llama-3.1-8b-instruct"
    use_llm: bool = True
    allow_custom_llm_endpoint: bool = False
    nvidia_api_key_env: str = "NVIDIA_API_KEY"
    openai_api_key_env: str = "OPENAI_API_KEY"
    gemini_api_key_env: str = "GEMINI_API_KEY"
    groq_api_key_env: str = "GROQ_API_KEY"
    xai_api_key_env: str = "XAI_API_KEY"
    enable_desktop_commands: bool = True
    allow_power_commands: bool = False
    input_mode: str = "auto"
    ui_mode: str = "auto"
    require_name_prefix: bool = False
    activation_mode: str = "wake_word"
    wake_words: list[str] = field(default_factory=lambda: ["гарфилд"])
    wake_window_sec: int = 12
    voice_activation_threshold: float = 0.008
    recognition_confidence_threshold: float = 0.35
    wake_word_confidence_threshold: float = 0.3
    command_confirmation_timeout_sec: int = 20
    confirm_phrases: list[str] = field(default_factory=lambda: ["да", "подтверждаю"])
    cancel_phrases: list[str] = field(default_factory=lambda: ["нет", "отмена", "отмени", "не надо"])
    screen_hints_enabled: bool = True
    remember_turns: int = 6
    auto_listen: bool = True
    tts_enabled: bool = True
    max_cached_answers: int = 120
    answer_cache_ttl_sec: int = 900
    persist_session_history: bool = False
    redact_sensitive_logs: bool = True
    history_retention_days: int = 7
    log_max_bytes: int = 2_000_000
    log_backup_count: int = 3
    skills_path: str = ""
    input_device_index: int | None = None
    output_device_index: int | None = None
    tts_voice: str = "ru-RU-SvetlanaNeural"
    piper_model_path: str = ""
    piper_config_path: str = ""

    @classmethod
    def load(
        cls,
        path: Path,
        secret_store: SecretStore | None = None,
    ) -> "FlagshipConfig":
        raw_data, load_warnings = load_json_config(path)
        if raw_data:
            if migrate_plaintext_secrets(
                raw_data,
                secret_store or SecretStore(),
            ):
                atomic_write_text(
                    path,
                    json.dumps(raw_data, ensure_ascii=False, indent=2) + "\n",
                )

        data = dict(raw_data)
        if "use_llm" not in data and "use_ollama" in data:
            data["use_llm"] = bool(data["use_ollama"])

        valid_fields = {field.name for field in fields(cls)}
        filtered_data = {key: value for key, value in data.items() if key in valid_fields}
        config = cls(**{**asdict(cls()), **filtered_data})
        config.load_warnings = load_warnings
        env_model_path = os.getenv("GARFIELD_VOSK_MODEL_PATH", "").strip()
        env_llm_provider = os.getenv("GARFIELD_LLM_PROVIDER", "").strip()
        env_llm_url = os.getenv("GARFIELD_LLM_API_URL", "").strip()
        env_llm_model = os.getenv("GARFIELD_LLM_MODEL", "").strip()
        env_nvidia_key_env = os.getenv("GARFIELD_NVIDIA_API_KEY_ENV", "").strip()
        env_openai_key_env = os.getenv("GARFIELD_OPENAI_API_KEY_ENV", "").strip()
        env_gemini_key_env = os.getenv("GARFIELD_GEMINI_API_KEY_ENV", "").strip()
        env_groq_key_env = os.getenv("GARFIELD_GROQ_API_KEY_ENV", "").strip()
        env_xai_key_env = os.getenv("GARFIELD_XAI_API_KEY_ENV", "").strip()
        env_piper_model_path = os.getenv("GARFIELD_PIPER_MODEL_PATH", "").strip()
        env_piper_config_path = os.getenv("GARFIELD_PIPER_CONFIG_PATH", "").strip()
        env_skills_path = os.getenv("GARFIELD_SKILLS_PATH", "").strip()

        if env_model_path:
            config.vosk_model_path = env_model_path
        if env_llm_provider:
            config.llm_provider = env_llm_provider
        if env_llm_url:
            config.llm_api_url = env_llm_url
        if env_llm_model:
            config.llm_model = env_llm_model
        if env_nvidia_key_env:
            config.nvidia_api_key_env = env_nvidia_key_env
        if env_openai_key_env:
            config.openai_api_key_env = env_openai_key_env
        if env_gemini_key_env:
            config.gemini_api_key_env = env_gemini_key_env
        if env_groq_key_env:
            config.groq_api_key_env = env_groq_key_env
        if env_xai_key_env:
            config.xai_api_key_env = env_xai_key_env
        if env_piper_model_path:
            config.piper_model_path = env_piper_model_path
        if env_piper_config_path:
            config.piper_config_path = env_piper_config_path
        if env_skills_path:
            config.skills_path = env_skills_path

        config_base_dir = path.resolve().parent
        config.vosk_model_path = str(
            resolve_config_path(
                config_base_dir,
                config.vosk_model_path or "models/vosk-model-ru-0.22",
            )
        )
        config.piper_model_path = str(
            resolve_config_path(
                config_base_dir,
                config.piper_model_path
                or "models/piper/ru_RU-irina-medium.onnx",
            )
        )
        config.piper_config_path = str(
            resolve_config_path(
                config_base_dir,
                config.piper_config_path
                or "models/piper/ru_RU-irina-medium.onnx.json",
            )
        )
        config.skills_path = str(
            resolve_config_path(
                config_base_dir,
                config.skills_path or "garfield_skills.json",
            )
        )

        config.input_mode = config.input_mode.lower().strip()
        config.ui_mode = config.ui_mode.lower().strip()
        config.llm_provider = core.normalize_llm_provider(config.llm_provider)
        if not config.llm_model:
            config.llm_model = core.default_llm_model(config.llm_provider)
        config.llm_api_url = core.validate_llm_api_url(
            config.llm_provider,
            core.default_llm_api_url(
                config.llm_provider,
                config.llm_api_url,
            ),
            allow_custom=config.allow_custom_llm_endpoint,
        )
        config.activation_mode = config.activation_mode.lower().strip()
        if config.activation_mode not in {"continuous", "wake_word"}:
            config.activation_mode = "continuous"
        if isinstance(config.wake_words, str):
            config.wake_words = [part.strip() for part in config.wake_words.split(",") if part.strip()]
        config.wake_words = [core.normalize_text(word) for word in config.wake_words if core.normalize_text(word)]
        if not config.wake_words:
            config.wake_words = ["гарфилд"]
        config.recognition_timeout_sec = clamp_int(
            config.recognition_timeout_sec,
            1,
            300,
            "recognition_timeout_sec",
        )
        config.wake_window_sec = clamp_int(
            config.wake_window_sec,
            3,
            60,
            "wake_window_sec",
        )
        config.voice_activation_threshold = max(0.0, min(float(config.voice_activation_threshold or 0.0), 0.1))
        config.recognition_confidence_threshold = max(
            0.0,
            min(float(config.recognition_confidence_threshold or 0.0), 1.0),
        )
        config.wake_word_confidence_threshold = max(
            0.0,
            min(float(config.wake_word_confidence_threshold or 0.0), 1.0),
        )
        config.command_confirmation_timeout_sec = clamp_int(
            config.command_confirmation_timeout_sec,
            5,
            120,
            "command_confirmation_timeout_sec",
        )
        config.remember_turns = clamp_int(
            config.remember_turns,
            1,
            100,
            "remember_turns",
        )
        config.max_cached_answers = clamp_int(
            config.max_cached_answers,
            1,
            10_000,
            "max_cached_answers",
        )
        config.answer_cache_ttl_sec = clamp_int(
            config.answer_cache_ttl_sec,
            1,
            86_400,
            "answer_cache_ttl_sec",
        )
        config.history_retention_days = clamp_int(
            config.history_retention_days,
            0,
            3_650,
            "history_retention_days",
        )
        config.log_max_bytes = clamp_int(
            config.log_max_bytes,
            1_024,
            100_000_000,
            "log_max_bytes",
        )
        config.log_backup_count = clamp_int(
            config.log_backup_count,
            0,
            100,
            "log_backup_count",
        )
        if isinstance(config.confirm_phrases, str):
            config.confirm_phrases = [part.strip() for part in config.confirm_phrases.split(",") if part.strip()]
        if isinstance(config.cancel_phrases, str):
            config.cancel_phrases = [part.strip() for part in config.cancel_phrases.split(",") if part.strip()]
        config.confirm_phrases = [core.normalize_text(phrase) for phrase in config.confirm_phrases if core.normalize_text(phrase)]
        config.cancel_phrases = [core.normalize_text(phrase) for phrase in config.cancel_phrases if core.normalize_text(phrase)]
        if not config.confirm_phrases:
            config.confirm_phrases = ["да", "подтверждаю"]
        if not config.cancel_phrases:
            config.cancel_phrases = ["нет", "отмена", "отмени", "не надо"]
        return config


@dataclass
class RuntimeEvent:
    kind: str
    text: str
    created_at: float
    sensitive: bool = False
    persist: bool = True


def _stored_secrets() -> list[str]:
    store = SecretStore()
    secrets: list[str] = []
    for provider in PROVIDERS:
        try:
            value = store.get(provider)
        except Exception:
            value = ""
        if value:
            secrets.append(value)
    return secrets


def setup_logging(config: FlagshipConfig) -> None:
    file_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding="utf-8",
    )
    stream_handler = logging.StreamHandler(sys.stdout)
    if config.redact_sensitive_logs:
        redacting_filter = SecretRedactingFilter(_stored_secrets)
        file_handler.addFilter(redacting_filter)
        stream_handler.addFilter(redacting_filter)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            file_handler,
            stream_handler,
        ],
        force=True,
    )


def save_config(config: FlagshipConfig, path: Path = CONFIG_PATH) -> None:
    atomic_write_text(
        path,
        json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n",
    )


class TTSQueue:
    def __init__(
        self,
        assistant_name: str,
        enabled: bool,
        output_device_index: int | None = None,
        tts_voice: str = "ru-RU-SvetlanaNeural",
        piper_model_path: str = "",
        piper_config_path: str = "",
    ) -> None:
        self.speaker = core.Speaker(
            assistant_name,
            output_device_index,
            tts_voice,
            piper_model_path,
            piper_config_path,
        )
        self.enabled = enabled
        self.queue: queue.Queue[str | None] = queue.Queue(maxsize=32)
        self.stop_event = threading.Event()
        self.busy_event = threading.Event()
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.started = False

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        self.speaker.warmup()
        self.worker.start()

    def stop(self) -> None:
        if not self.started:
            return
        self.stop_event.set()
        self.speaker.interrupt()
        while True:
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except queue.Empty:
                break
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            logging.warning("Не удалось остановить очередь озвучки штатно.")
        self.worker.join(timeout=5)

    def speak(self, text: str) -> None:
        if self.enabled and text.strip():
            try:
                self.queue.put_nowait(text)
            except queue.Full:
                logging.warning("Очередь озвучки заполнена.")

    def interrupt(self) -> None:
        self.speaker.interrupt()
        while True:
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                break
            self.queue.task_done()

    def set_output_device(self, output_device_index: int | None) -> None:
        self.speaker.set_output_device(output_device_index)

    def set_voice(self, tts_voice: str) -> None:
        self.speaker.set_voice(tts_voice)

    def is_busy(self) -> bool:
        return self.busy_event.is_set() or not self.queue.empty()

    def _worker_loop(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                self.queue.task_done()
                return
            self.busy_event.set()
            try:
                self.speaker.speak(item)
            except Exception as error:
                logging.warning("Ошибка озвучки: %s", error)
            finally:
                self.speaker.clear_interrupt()
                self.busy_event.clear()
                self.queue.task_done()


class FlagshipRuntime:
    def __init__(self, config: FlagshipConfig) -> None:
        self.config = config
        self.assistant = core.AssistantCore(config)
        self.keyboard_input = core.KeyboardInput()
        self.voice_recognizer: core.VoiceRecognizer | None = None
        self.input_mode = "keyboard"
        self.listening_enabled = False
        self.stop_event = threading.Event()
        self.tts = TTSQueue(
            config.assistant_name,
            config.tts_enabled,
            config.output_device_index,
            config.tts_voice,
            config.piper_model_path,
            config.piper_config_path,
        )
        self.events: queue.Queue[RuntimeEvent] = queue.Queue(maxsize=256)
        self.command_queue: queue.Queue[tuple[str, str] | None] = queue.Queue(
            maxsize=64
        )
        self.command_worker = threading.Thread(target=self._command_worker_loop, daemon=True)
        self.voice_worker: threading.Thread | None = None
        self.listening_lock = threading.Lock()
        self.audio_lock = threading.RLock()
        self.voice_cancel_event = threading.Event()
        self.voice_generation = 0
        self.started = False
        self.session_lines: deque[str] = deque(maxlen=2_000)
        self.wake_active_until = 0.0
        self.command_worker_last_activity = time.monotonic()
        self.command_worker_last_error: str | None = None

    def start(self) -> None:
        if self.started:
            return

        self._prune_expired_history()
        self._prepare_inputs()
        self.tts.start()
        self.command_worker.start()
        self.started = True

        for line in self._build_diagnostics():
            self.emit("status", line)
        for warning in getattr(self.config, "load_warnings", []):
            self.emit("status", warning)

        startup = (
            f"{self.config.assistant_name} готов к работе. "
            f"Режим ввода: {self.input_mode}. "
            "Скажите помощь, чтобы узнать возможности."
        )
        self.emit("assistant", startup)
        self.tts.speak(startup)

        if self.voice_recognizer and self.config.auto_listen:
            self.set_listening(True)

    def stop(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        with self.audio_lock:
            self._stop_voice_worker_locked()
            recognizer = self.voice_recognizer
            self.voice_recognizer = None
            if recognizer is not None:
                recognizer.close()
        while True:
            try:
                self.command_queue.get_nowait()
                self.command_queue.task_done()
            except queue.Empty:
                break
        try:
            self.command_queue.put_nowait(None)
        except queue.Full:
            logging.warning("Не удалось добавить сигнал остановки command worker.")
        self.tts.stop()
        if self.command_worker.is_alive():
            self.command_worker.join(timeout=5)
        self._save_session_history()

    def emit(
        self,
        kind: str,
        text: str,
        *,
        sensitive: bool = False,
        persist: bool = True,
    ) -> None:
        visible_text = text
        stored_text = (
            "[Чувствительные данные скрыты]"
            if sensitive
            else redact_sensitive_text(text, self._known_secrets())
        )
        if persist and self.config.persist_session_history:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.session_lines.append(
                f"{timestamp} | {kind.upper()}: {stored_text}"
            )
        self._put_event(
            RuntimeEvent(
                kind=kind,
                text=visible_text,
                created_at=time.time(),
                sensitive=sensitive,
                persist=persist,
            )
        )

    def _put_event(self, event: RuntimeEvent) -> None:
        try:
            self.events.put_nowait(event)
        except queue.Full:
            if event.kind in {"progress", "status"}:
                return
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
            try:
                self.events.put_nowait(event)
            except queue.Full:
                logging.warning("Очередь GUI-событий заполнена.")

    def _known_secrets(self) -> list[str]:
        return self.assistant._known_secrets()

    def submit_text(self, text: str, source: str = "manual") -> bool:
        normalized = core.normalize_text(text)
        if not normalized:
            return False
        if len(normalized) > 8_000:
            self.emit("assistant", "Команда слишком длинная.")
            return False
        if self._is_stop_speaking_command(normalized):
            self.tts.interrupt()
        try:
            self.command_queue.put_nowait((normalized, source))
        except queue.Full:
            self.emit(
                "assistant",
                "Очередь команд заполнена. Дождитесь выполнения предыдущих действий.",
            )
            return False
        return True

    def _is_stop_speaking_command(self, text: str) -> bool:
        stop_phrases = (
            "\u0433\u0430\u0440\u0444\u0438\u043b\u0434 \u0441\u0442\u043e\u043f",
            "\u0441\u0442\u043e\u043f \u0433\u0430\u0440\u0444\u0438\u043b\u0434",
            "\u0433\u0430\u0440\u0444\u0438\u043b\u0434 \u0437\u0430\u043c\u043e\u043b\u0447\u0438",
            "\u0433\u0430\u0440\u0444\u0438\u043b\u0434 \u043f\u0440\u0435\u043a\u0440\u0430\u0442\u0438",
            "\u0437\u0430\u043c\u043e\u043b\u0447\u0438",
            "\u043f\u0440\u0435\u043a\u0440\u0430\u0442\u0438 \u0433\u043e\u0432\u043e\u0440\u0438\u0442\u044c",
            "\u0441\u0442\u043e\u043f \u043e\u0442\u0432\u0435\u0442",
        )
        return core.contains_any(text, stop_phrases)

    def _detect_voice_interrupt(self, text: str) -> bool:
        normalized = core.normalize_text(text)
        if not normalized:
            return False
        if self._is_stop_speaking_command(normalized):
            return True
        interrupt_verbs = (
            "\u0441\u0442\u043e\u043f",
            "\u0437\u0430\u043c\u043e\u043b\u0447\u0438",
            "\u043f\u0440\u0435\u043a\u0440\u0430\u0442\u0438",
        )
        return any(wake_word in normalized and core.contains_any(normalized, interrupt_verbs) for wake_word in self.config.wake_words)

    def drain_events(self) -> list[RuntimeEvent]:
        items: list[RuntimeEvent] = []
        while True:
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                return items

    def set_listening(self, enabled: bool) -> None:
        with self.listening_lock, self.audio_lock:
            if not self.voice_recognizer:
                self.listening_enabled = False
                self.emit("status", "Голосовой ввод недоступен. Используйте текстовый режим.")
                return

            if self.listening_enabled == enabled:
                return

            self.listening_enabled = enabled
            self.emit("status", "Прослушивание включено." if enabled else "Прослушивание остановлено.")

            if enabled:
                self._start_voice_worker_locked()
            else:
                self._stop_voice_worker_locked()

    def _prepare_inputs(self) -> None:
        if self.config.input_mode == "keyboard":
            self.input_mode = "keyboard"
            return

        try:
            self.voice_recognizer = core.VoiceRecognizer(
                Path(self.config.vosk_model_path),
                input_device_index=self.config.input_device_index,
            )
            self.input_mode = "voice"
        except Exception as error:
            if self.config.input_mode == "voice":
                raise
            self.voice_recognizer = None
            self.input_mode = "keyboard"
            self.emit("status", f"Голосовой ввод недоступен, переключаюсь на keyboard: {error}")

    def apply_audio_settings(
        self,
        input_device_index: int | None,
        output_device_index: int | None,
        activation_mode: str | None = None,
        wake_words: list[str] | None = None,
        wake_window_sec: int | None = None,
        voice_activation_threshold: float | None = None,
        recognition_confidence_threshold: float | None = None,
        wake_word_confidence_threshold: float | None = None,
    ) -> str:
        with self.audio_lock:
            was_listening = self.listening_enabled
            self._stop_voice_worker_locked()
            old_recognizer = self.voice_recognizer
            self.voice_recognizer = None
            if old_recognizer is not None:
                old_recognizer.close()

            self.config.input_device_index = input_device_index
            self.config.output_device_index = output_device_index
            if activation_mode is not None:
                self.config.activation_mode = activation_mode
            if wake_words is not None:
                cleaned = [core.normalize_text(word) for word in wake_words if core.normalize_text(word)]
                self.config.wake_words = cleaned or ["гарфилд"]
            if wake_window_sec is not None:
                self.config.wake_window_sec = max(3, min(int(wake_window_sec), 60))
            if voice_activation_threshold is not None:
                self.config.voice_activation_threshold = max(0.0, min(float(voice_activation_threshold), 0.1))
            if recognition_confidence_threshold is not None:
                self.config.recognition_confidence_threshold = max(0.0, min(float(recognition_confidence_threshold), 1.0))
            if wake_word_confidence_threshold is not None:
                self.config.wake_word_confidence_threshold = max(0.0, min(float(wake_word_confidence_threshold), 1.0))
            self.tts.set_output_device(output_device_index)
            self._prepare_inputs()
            self.voice_generation += 1

            if was_listening and self.voice_recognizer:
                self.listening_enabled = True
                self._start_voice_worker_locked()

        if was_listening and not self.voice_recognizer:
            self.emit("status", "Прослушивание остановлено: после смены устройства микрофон недоступен.")

        return (
            f"Микрофон: {core.describe_audio_device('input', self.config.input_device_index)}. "
            f"Вывод: {core.describe_audio_device('output', self.config.output_device_index)}."
        )

    def reload_skills(self) -> str:
        count, error = self.assistant.skills.reload()
        if error:
            return f"Не удалось загрузить навыки: {error}"
        return f"Навыки обновлены. Активно {count}."

    def open_skills_file(self) -> str:
        path = Path(self.config.skills_path)
        if not path.exists():
            raise FileNotFoundError(f"Файл навыков не найден: {path}")
        os.startfile(str(path))
        return f"Открываю {path.name}."

    def _activation_mode_label(self) -> str:
        return "по ключевой фразе" if self.config.activation_mode == "wake_word" else "непрерывный"

    def _skills_state_text(self) -> str:
        if self.assistant.skills.load_error:
            return f"ошибка: {self.assistant.skills.load_error}"
        return f"{self.assistant.skills.count()} загружено"

    def _build_diagnostics(self) -> list[str]:
        llm_state = "доступен" if self.assistant.llm_client and self.assistant.llm_client.is_available() else "недоступен"
        llm_label = core.describe_llm_provider(self.config.llm_provider)
        vosk_state = "найдена" if Path(self.config.vosk_model_path).exists() else "не найдена"
        piper_state = "готов" if Path(self.config.piper_model_path).exists() and Path(self.config.piper_config_path).exists() else "недоступен"
        gui_state = "доступен" if tk is not None else "недоступен"
        return [
            f"Vosk-модель: {vosk_state}.",
            f"Piper: {piper_state}.",
            f"ИИ-провайдер: {llm_label}, {llm_state}.",
            f"GUI: {gui_state}.",
            f"Режим активации: {self._activation_mode_label()}.",
            f"Ключевая фраза: {', '.join(self.config.wake_words)}.",
            f"Шумовой порог: {int(self.config.voice_activation_threshold * 1000)}.",
            f"Уверенность распознавания: {int(self.config.recognition_confidence_threshold * 100)}%.",
            f"Уверенность ключевой фразы: {int(self.config.wake_word_confidence_threshold * 100)}%.",
            f"Навыки: {self._skills_state_text()}.",
            f"TTS: {'включен' if self.config.tts_enabled else 'отключен'}.",
            f"Микрофон: {core.describe_audio_device('input', self.config.input_device_index)}.",
            f"Вывод: {core.describe_audio_device('output', self.config.output_device_index)}.",
            f"Силовые команды: {'включены' if self.config.allow_power_commands else 'отключены'}.",
        ]

    def _prepare_voice_text(self, text: str) -> str | None:
        if self.config.activation_mode != "wake_word":
            return text

        normalized = core.normalize_text(text)
        if not normalized:
            return None

        now = time.time()
        if now < self.wake_active_until:
            return normalized

        for wake_word in self.config.wake_words:
            if wake_word not in normalized:
                continue
            _, _, tail = normalized.partition(wake_word)
            remainder = tail.strip(" ,.!?-")
            self.wake_active_until = now + self.config.wake_window_sec
            if not remainder:
                self.emit("status", f"Ключевая фраза принята. Слушаю {self.config.wake_window_sec} секунд.")
                return None
            return remainder
        return None

    def _voice_worker_loop(self) -> None:
        while not self.stop_event.is_set():
            recognizer = self.voice_recognizer
            generation = self.voice_generation
            cancel_event = self.voice_cancel_event
            if not self.listening_enabled or not recognizer:
                time.sleep(0.2)
                continue
            if self.tts.is_busy():
                try:
                    interrupt_text = recognizer.listen(
                        1,
                        min_rms=max(0.01, self.config.voice_activation_threshold * 1.5),
                        min_confidence=self.config.wake_word_confidence_threshold,
                        cancel_event=cancel_event,
                    )
                except Exception:
                    if cancel_event.is_set():
                        return
                    time.sleep(0.2)
                    continue
                if generation != self.voice_generation or cancel_event.is_set():
                    return
                if interrupt_text and self._detect_voice_interrupt(interrupt_text):
                    self.submit_text("гарфилд стоп", source="voice-interrupt")
                continue

            try:
                text = recognizer.listen(
                    self.config.recognition_timeout_sec,
                    min_rms=self.config.voice_activation_threshold,
                    min_confidence=(
                        self.config.wake_word_confidence_threshold
                        if self.config.activation_mode == "wake_word" and time.time() >= self.wake_active_until
                        else self.config.recognition_confidence_threshold
                    ),
                    cancel_event=cancel_event,
                )
            except Exception as error:
                if cancel_event.is_set() or generation != self.voice_generation:
                    return
                self.emit("status", f"Ошибка распознавания речи: {error}")
                time.sleep(1)
                continue

            if generation != self.voice_generation or cancel_event.is_set():
                return
            if text:
                prepared = self._prepare_voice_text(text)
                if prepared:
                    self.submit_text(prepared, source="voice")

    def _command_worker_loop(self) -> None:
        while True:
            try:
                item = self.command_queue.get(timeout=0.2)
            except queue.Empty:
                if self.stop_event.is_set():
                    return
                continue

            self.command_worker_last_activity = time.monotonic()
            try:
                if item is None:
                    return
                text, source = item
                self._process_command(text, source)
            except Exception:
                error_id = uuid.uuid4().hex[:8]
                self.command_worker_last_error = error_id
                logging.exception(
                    "Необработанная ошибка command worker. error_id=%s",
                    error_id,
                )
                self.emit(
                    "assistant",
                    (
                        "Не удалось выполнить команду. "
                        f"Код ошибки: {error_id}. Подробности записаны в журнал."
                    ),
                )
            finally:
                self.command_worker_last_activity = time.monotonic()
                self.command_queue.task_done()

    def _start_voice_worker_locked(self) -> None:
        if self.voice_worker is not None and self.voice_worker.is_alive():
            return
        self.voice_cancel_event = threading.Event()
        self.voice_worker = threading.Thread(
            target=self._voice_worker_loop,
            daemon=True,
        )
        self.voice_worker.start()

    def _stop_voice_worker_locked(self) -> None:
        self.listening_enabled = False
        self.voice_cancel_event.set()
        worker = self.voice_worker
        if (
            worker
            and worker.is_alive()
            and worker is not threading.current_thread()
        ):
            worker.join(timeout=5)
        self.voice_worker = None

    def _stop_voice_worker(self) -> None:
        with self.audio_lock:
            self._stop_voice_worker_locked()

    def _process_command(self, text: str, source: str) -> None:
        if looks_sensitive(text):
            self.emit(
                "user",
                f"[{source}] Команда локального ввода текста",
                sensitive=True,
            )
        else:
            self.emit("user", f"[{source}] {text}")
        self.emit("progress", self._command_progress_text(text))

        runtime_reply = self._handle_runtime_command(text)
        if runtime_reply is not None:
            self._publish_reply(runtime_reply)
            return

        reply = self.assistant.handle(text)
        if reply is None:
            self.emit("status", "Команда проигнорирована.")
            return

        self._publish_reply(reply)

    def _publish_reply(self, reply: core.AssistantReply) -> None:
        if reply.text:
            self.emit("assistant", reply.text)
            if reply.should_speak:
                self.tts.speak(reply.text)

        if reply.should_exit:
            self.stop_event.set()

    def _command_progress_text(self, text: str) -> str:
        if self._is_stop_speaking_command(text):
            return "Останавливаю озвучку..."
        if core.contains_any(text, ("диагностика", "статус системы", "покажи статус", "покажи диагностику")):
            return "Собираю диагностику..."
        if core.contains_any(text, ("очисти", "сбрось", "сохрани", "экспорт")):
            return "Выполняю команду..."
        if core.contains_any(text, ("открой", "запусти", "покажи файл", "покажи папку")):
            return "Открываю..."
        if text.startswith("найди ") or text.startswith("поиск ") or core.contains_any(text, ("гугл ", "ютуб ", "youtube ")):
            return "Ищу..."
        if core.contains_any(text, ("включи", "выключи", "старт", "стоп", "слушай", "не слушай")):
            return "Переключаю режим..."
        return "Думаю..."

    def _handle_runtime_command(self, text: str) -> core.AssistantReply | None:
        if core.contains_any(text, ("диагностика", "статус системы", "покажи статус", "покажи диагностику")):
            return core.AssistantReply(self._runtime_status_text())

        if self._is_stop_speaking_command(text):
            self.tts.interrupt()
            return core.AssistantReply("Останавливаюсь.", should_speak=False)

        if core.contains_any(text, ("выключи озвучку", "режим тишины", "тихий режим", "без озвучки")):
            self.tts.enabled = False
            return core.AssistantReply("Озвучка отключена.", should_speak=False)

        if core.contains_any(text, ("включи озвучку", "голосовой режим")):
            self.tts.enabled = True
            return core.AssistantReply("Озвучка включена.")

        if core.contains_any(text, ("включи прослушивание", "старт прослушивания", "слушай")):
            self.set_listening(True)
            return core.AssistantReply("Прослушивание включено.")

        if core.contains_any(text, ("выключи прослушивание", "стоп прослушивания", "не слушай")):
            self.set_listening(False)
            return core.AssistantReply("Прослушивание остановлено.")

        if core.contains_any(text, ("очисти память", "сбрось диалог", "очисти диалог")):
            self.assistant.history.turns.clear()
            self.assistant.last_answer = ""
            self.assistant.last_user_command = ""
            self.assistant.previous_user_command = ""
            return core.AssistantReply("Память диалога очищена.")

        if core.contains_any(text, ("очисти кэш", "сбрось кэш")):
            if hasattr(self.assistant, "answer_cache"):
                self.assistant.answer_cache.clear()
            return core.AssistantReply("Кэш ответов очищен.")

        if core.contains_any(text, ("сохрани диалог", "сохрани историю", "экспорт диалога")):
            path = self._save_session_history()
            return core.AssistantReply(f"История сохранена в файл {path.name}.", should_speak=False)

        if core.contains_any(text, ("открой папку проекта", "покажи папку проекта")):
            try:
                os.startfile(str(BASE_DIR))
                return core.AssistantReply("Открываю папку проекта.")
            except Exception as error:
                return core.AssistantReply(f"Не удалось открыть папку проекта: {error}", should_speak=False)

        if core.contains_any(text, ("включи режим по ключевой фразе", "режим по имени", "wake word")):
            self.config.activation_mode = "wake_word"
            self.wake_active_until = 0.0
            return core.AssistantReply(f"Включен режим по ключевой фразе: {', '.join(self.config.wake_words)}.")

        if core.contains_any(text, ("включи непрерывный режим", "слушай без имени", "continuous mode")):
            self.config.activation_mode = "continuous"
            return core.AssistantReply("Включен непрерывный голосовой режим.")

        if core.contains_any(text, ("какая ключевая фраза", "покажи ключевую фразу", "wake phrase")):
            return core.AssistantReply(f"Ключевая фраза: {', '.join(self.config.wake_words)}.", should_speak=False)

        if core.contains_any(text, ("обнови навыки", "перезагрузи навыки", "reload skills")):
            return core.AssistantReply(self.reload_skills(), should_speak=False)

        if core.contains_any(text, ("открой файл навыков", "покажи файл навыков", "open skills file")):
            try:
                return core.AssistantReply(self.open_skills_file(), should_speak=False)
            except Exception as error:
                return core.AssistantReply(f"Не удалось открыть файл навыков: {error}", should_speak=False)

        return None

    def _runtime_status_text(self) -> str:
        llm_state = "доступен" if self.assistant.llm_client and self.assistant.llm_client.is_available() else "недоступен"
        llm_label = core.describe_llm_provider(self.config.llm_provider)
        vosk_state = "готов" if self.voice_recognizer is not None else "недоступен"
        piper_state = "готов" if Path(self.config.piper_model_path).exists() and Path(self.config.piper_config_path).exists() else "недоступен"
        listening_state = "включено" if self.listening_enabled else "выключено"
        tts_state = "включена" if self.tts.enabled else "выключена"
        cache_size = len(getattr(self.assistant, "answer_cache", {}))
        dialog_size = len(self.assistant.history.turns)
        return (
            f"Режим ввода: {self.input_mode}. "
            f"Прослушивание: {listening_state}. "
            f"TTS: {tts_state}. "
            f"Vosk: {vosk_state}. "
            f"Piper: {piper_state}. "
            f"ИИ-провайдер: {llm_label}, {llm_state}. "
            f"Режим активации: {self._activation_mode_label()}. "
            f"Ключевая фраза: {', '.join(self.config.wake_words)}. "
            f"Шумовой порог: {int(self.config.voice_activation_threshold * 1000)}. "
            f"Уверенность: {int(self.config.recognition_confidence_threshold * 100)}%. "
            f"Навыки: {self._skills_state_text()}. "
            f"Микрофон: {core.describe_audio_device('input', self.config.input_device_index)}. "
            f"Вывод: {core.describe_audio_device('output', self.config.output_device_index)}. "
            f"Память диалога: {dialog_size}. "
            f"Кэш ответов: {cache_size}."
        )

    def _save_session_history(self) -> Path:
        if not self.session_lines:
            return SESSION_LOG_PATH
        atomic_write_text(
            SESSION_LOG_PATH,
            "\n".join(self.session_lines) + "\n",
        )
        return SESSION_LOG_PATH

    def _prune_expired_history(self) -> None:
        retention_days = max(0, int(self.config.history_retention_days))
        cutoff = time.time() - retention_days * 86_400
        paths = (
            SESSION_LOG_PATH,
            BASE_DIR / "garfield_session_history_export.txt",
            BASE_DIR / "garfield_session_history_export.json",
        )
        for path in paths:
            try:
                if path.exists() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError as error:
                logging.warning(
                    "Не удалось удалить устаревший файл истории %s: %s",
                    path.name,
                    error,
                )


class FlagshipGUI:
    def __init__(self, runtime: FlagshipRuntime) -> None:
        if tk is None or scrolledtext is None:
            raise RuntimeError("Tkinter недоступен.")

        self.runtime = runtime
        self.root = tk.Tk()
        self.root.title("Garfield Flagship")
        self.root.geometry("980x700")
        self.root.minsize(820, 560)

        self.status_var = tk.StringVar(value="Инициализация...")
        self.listening_var = tk.StringVar(value="Прослушивание: выкл")
        self.input_var = tk.StringVar()
        self.settings_window: tk.Toplevel | None = None
        self.settings_status_var: tk.StringVar | None = None
        self.settings_input_var: tk.StringVar | None = None
        self.settings_output_var: tk.StringVar | None = None
        self.settings_activation_var: tk.StringVar | None = None
        self.settings_wake_words_var: tk.StringVar | None = None
        self.settings_wake_window_var: tk.StringVar | None = None
        self.settings_noise_gate_var: tk.DoubleVar | None = None
        self.settings_input_combo: ttk.Combobox | None = None
        self.settings_output_combo: ttk.Combobox | None = None
        self.settings_activation_combo: ttk.Combobox | None = None
        self.settings_input_options: dict[str, int | None] = {}
        self.settings_output_options: dict[str, int | None] = {}
        self.mic_test_monitor: core.AudioLevelMonitor | None = None
        self.mic_meter_canvas: tk.Canvas | None = None
        self.mic_meter_items: list[int] = []
        self.is_closing = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(120, self._present_window)
        self.root.after(700, self._present_window)
        self.root.after(1600, self._present_window)

    def _present_window(self) -> None:
        if not self.root.winfo_exists():
            return
        try:
            self.root.update_idletasks()
            try:
                self.root.state("normal")
            except tk.TclError:
                pass
            width = max(self.root.winfo_width(), 980)
            height = max(self.root.winfo_height(), 700)
            screen_width = max(self.root.winfo_screenwidth(), width)
            screen_height = max(self.root.winfo_screenheight(), height)
            x = max((screen_width - width) // 2, 0)
            y = max((screen_height - height) // 2, 0)
            self.root.geometry(f"{width}x{height}+{x}+{y}")
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.root.attributes("-topmost", True)
            self.root.after(350, lambda: self.root.winfo_exists() and self.root.attributes("-topmost", False))
            if os.name == "nt":
                try:
                    hwnd = self.root.winfo_id()
                    ctypes.windll.user32.ShowWindow(hwnd, 9)
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                except Exception:
                    pass
        except tk.TclError:
            return

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, padx=12, pady=12)
        header.pack(fill=tk.X)

        tk.Label(header, text="Garfield Flagship", font=("Segoe UI", 18, "bold"), anchor="w").pack(fill=tk.X)
        tk.Label(header, textvariable=self.status_var, font=("Segoe UI", 10), anchor="w", fg="#1f4f7a").pack(fill=tk.X, pady=(4, 0))
        tk.Label(header, textvariable=self.listening_var, font=("Segoe UI", 10), anchor="w", fg="#3d6f44").pack(fill=tk.X, pady=(2, 0))

        actions = tk.Frame(self.root, padx=12, pady=4)
        actions.pack(fill=tk.X)

        tk.Button(actions, text="Старт прослушивания", command=lambda: self._toggle_listening(True)).pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="Стоп прослушивания", command=lambda: self._toggle_listening(False)).pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="Помощь", command=lambda: self.runtime.submit_text("помощь", source="gui")).pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="Повтори", command=lambda: self.runtime.submit_text("повтори", source="gui")).pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="Статус", command=lambda: self.runtime.submit_text("диагностика", source="gui")).pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="Звук", command=self.open_audio_settings).pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="Сохранить диалог", command=lambda: self.runtime.submit_text("сохрани диалог", source="gui")).pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="Очистить кэш", command=lambda: self.runtime.submit_text("очисти кэш", source="gui")).pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="Выход", command=self.on_close).pack(side=tk.RIGHT, padx=4)

        self.log_widget = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, font=("Consolas", 11), padx=12, pady=12)
        self.log_widget.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
        self.log_widget.configure(state=tk.DISABLED)

        footer = tk.Frame(self.root, padx=12, pady=8)
        footer.pack(fill=tk.X)

        entry = tk.Entry(footer, textvariable=self.input_var, font=("Segoe UI", 11))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry.bind("<Return>", lambda event: self._submit_manual())
        tk.Button(footer, text="Отправить", command=self._submit_manual).pack(side=tk.LEFT, padx=(8, 0))

    def run(self) -> None:
        self.runtime.start()
        self._poll_events()
        self.root.mainloop()

    def _poll_events(self) -> None:
        for event in self.runtime.drain_events():
            self._append_event(event)
        if not self.runtime.stop_event.is_set():
            self.root.after(150, self._poll_events)
        else:
            self.status_var.set("Ассистент остановлен.")
            if not self.is_closing:
                self.root.after(50, self._shutdown_from_runtime)

    def _append_event(self, event: RuntimeEvent) -> None:
        timestamp = datetime.fromtimestamp(event.created_at).strftime("%H:%M:%S")
        prefix_map = {"assistant": "Гарфилд", "user": "Вы", "status": "Система"}
        line = f"{timestamp} | {prefix_map.get(event.kind, event.kind.title())}: {event.text}\n"

        if event.kind == "status":
            self.status_var.set(event.text)
        elif event.kind == "progress":
            self.status_var.set(event.text)
        elif event.kind == "assistant":
            self.status_var.set("Готов. Ожидаю команду.")

        self.log_widget.configure(state=tk.NORMAL)
        self.log_widget.insert(tk.END, line)
        self.log_widget.see(tk.END)
        self.log_widget.configure(state=tk.DISABLED)

    def _toggle_listening(self, enabled: bool) -> None:
        self.runtime.set_listening(enabled)
        self.listening_var.set("Прослушивание: вкл" if enabled else "Прослушивание: выкл")

    def _submit_manual(self) -> None:
        text = self.input_var.get().strip()
        if text:
            self.input_var.set("")
            self.runtime.submit_text(text, source="manual")

    def open_audio_settings(self) -> None:
        if ttk is None:
            if messagebox:
                messagebox.showerror("Звук", "Tkinter ttk недоступен.")
            return

        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        window.title("Настройки звука")
        window.geometry("660x620")
        window.minsize(620, 560)
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self._close_audio_settings)

        self.settings_window = window
        self.settings_status_var = tk.StringVar(value="Выберите устройства и проверьте звук.")
        self.settings_input_var = tk.StringVar()
        self.settings_output_var = tk.StringVar()
        self.settings_activation_var = tk.StringVar()
        self.settings_wake_words_var = tk.StringVar()
        self.settings_wake_window_var = tk.StringVar()
        self.settings_noise_gate_var = tk.DoubleVar()

        body = tk.Frame(window, padx=16, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(body, text="Аудионастройки", font=("Segoe UI", 16, "bold"), anchor="w").pack(fill=tk.X)
        tk.Label(
            body,
            text="Можно выбрать микрофон и выход, увидеть уровень сигнала и выполнить тесты как в Discord.",
            font=("Segoe UI", 10),
            anchor="w",
            justify=tk.LEFT,
            fg="#355c7d",
        ).pack(fill=tk.X, pady=(6, 14))

        grid = tk.Frame(body)
        grid.pack(fill=tk.X)
        grid.columnconfigure(1, weight=1)

        tk.Label(grid, text="Микрофон", font=("Segoe UI", 10, "bold"), anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 8))
        input_combo = ttk.Combobox(grid, textvariable=self.settings_input_var, state="readonly")
        input_combo.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=(0, 8))
        self.settings_input_combo = input_combo

        tk.Label(grid, text="Вывод", font=("Segoe UI", 10, "bold"), anchor="w").grid(row=1, column=0, sticky="w", pady=(0, 8))
        output_combo = ttk.Combobox(grid, textvariable=self.settings_output_var, state="readonly")
        output_combo.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(0, 8))
        self.settings_output_combo = output_combo

        tk.Label(grid, text="Голосовой режим", font=("Segoe UI", 10, "bold"), anchor="w").grid(row=2, column=0, sticky="w", pady=(8, 8))
        activation_combo = ttk.Combobox(
            grid,
            textvariable=self.settings_activation_var,
            state="readonly",
            values=["Всегда слушать", "По ключевой фразе"],
        )
        activation_combo.grid(row=2, column=1, sticky="ew", padx=(12, 0), pady=(8, 8))
        self.settings_activation_combo = activation_combo

        tk.Label(grid, text="Ключевая фраза", font=("Segoe UI", 10, "bold"), anchor="w").grid(row=3, column=0, sticky="w", pady=(0, 8))
        tk.Entry(grid, textvariable=self.settings_wake_words_var, font=("Segoe UI", 10)).grid(row=3, column=1, sticky="ew", padx=(12, 0), pady=(0, 8))

        tk.Label(grid, text="Окно активации, сек", font=("Segoe UI", 10, "bold"), anchor="w").grid(row=4, column=0, sticky="w", pady=(0, 8))
        tk.Entry(grid, textvariable=self.settings_wake_window_var, font=("Segoe UI", 10)).grid(row=4, column=1, sticky="ew", padx=(12, 0), pady=(0, 8))

        tk.Label(grid, text="Шумовой порог", font=("Segoe UI", 10, "bold"), anchor="w").grid(row=5, column=0, sticky="w", pady=(0, 8))
        noise_frame = tk.Frame(grid)
        noise_frame.grid(row=5, column=1, sticky="ew", padx=(12, 0), pady=(0, 8))
        noise_frame.columnconfigure(0, weight=1)
        tk.Scale(
            noise_frame,
            from_=0,
            to=40,
            orient=tk.HORIZONTAL,
            resolution=1,
            showvalue=True,
            variable=self.settings_noise_gate_var,
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            noise_frame,
            text="Чем выше значение, тем сильнее фильтрация фона.",
            font=("Segoe UI", 9),
            fg="#5a5a5a",
            anchor="w",
        ).grid(row=1, column=0, sticky="ew")

        meter_frame = tk.Frame(body, pady=10)
        meter_frame.pack(fill=tk.X)
        tk.Label(meter_frame, text="Тест микрофона", font=("Segoe UI", 10, "bold"), anchor="w").pack(fill=tk.X)
        tk.Label(
            meter_frame,
            text="Говорите в микрофон. Чем громче сигнал, тем выше и ярче шкала.",
            font=("Segoe UI", 9),
            anchor="w",
            fg="#5a5a5a",
        ).pack(fill=tk.X, pady=(2, 8))
        self.mic_meter_canvas = tk.Canvas(meter_frame, height=42, highlightthickness=0, bg="#eef2f7")
        self.mic_meter_canvas.pack(fill=tk.X)
        self.mic_meter_items = []
        for index in range(24):
            x0 = 10 + index * 23
            x1 = x0 + 16
            item = self.mic_meter_canvas.create_rectangle(x0, 30, x1, 34, fill="#cfd8e3", outline="")
            self.mic_meter_items.append(item)

        button_row = tk.Frame(body, pady=14)
        button_row.pack(fill=tk.X)
        tk.Button(button_row, text="Обновить список", command=self._refresh_audio_settings).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(button_row, text="Тест микрофона", command=self._start_microphone_test).pack(side=tk.LEFT, padx=8)
        tk.Button(button_row, text="Стоп теста", command=self._stop_microphone_test).pack(side=tk.LEFT, padx=8)
        tk.Button(button_row, text="Тест сигнала", command=self._test_output_signal).pack(side=tk.LEFT, padx=8)
        tk.Button(button_row, text="Тест озвучки", command=self._test_output_speech).pack(side=tk.LEFT, padx=8)

        tk.Button(button_row, text="Файл навыков", command=self._open_skills_file).pack(side=tk.LEFT, padx=8)
        tk.Button(button_row, text="Обновить навыки", command=self._reload_skills).pack(side=tk.LEFT, padx=8)

        footer = tk.Frame(body)
        footer.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))
        tk.Label(footer, textvariable=self.settings_status_var, anchor="w", justify=tk.LEFT, fg="#1f4f7a").pack(fill=tk.X, pady=(0, 10))

        actions = tk.Frame(footer)
        actions.pack(fill=tk.X)
        tk.Button(actions, text="Применить", command=self._apply_audio_settings).pack(side=tk.RIGHT)
        tk.Button(actions, text="Закрыть", command=self._close_audio_settings).pack(side=tk.RIGHT, padx=(0, 8))

        input_combo["values"] = []
        output_combo["values"] = []
        self._refresh_audio_settings()

    def _refresh_audio_settings(self) -> None:
        if not self.settings_input_var or not self.settings_output_var or not self.settings_window:
            return

        try:
            input_devices = core.get_audio_devices("input")
            output_devices = core.get_audio_devices("output")
        except Exception as error:
            if self.settings_status_var:
                self.settings_status_var.set(f"Не удалось получить список устройств: {error}")
            return

        self.settings_input_options = {f"Авто: {core.describe_audio_device('input', None)}": None}
        for device in input_devices:
            self.settings_input_options[core.format_audio_device_label(device, "input")] = device.index

        self.settings_output_options = {f"Авто: {core.describe_audio_device('output', None)}": None}
        for device in output_devices:
            self.settings_output_options[core.format_audio_device_label(device, "output")] = device.index

        if self.settings_input_combo:
            self.settings_input_combo["values"] = list(self.settings_input_options.keys())
        if self.settings_output_combo:
            self.settings_output_combo["values"] = list(self.settings_output_options.keys())

        self.settings_input_var.set(self._current_audio_label("input"))
        self.settings_output_var.set(self._current_audio_label("output"))
        if self.settings_activation_var:
            self.settings_activation_var.set("По ключевой фразе" if self.runtime.config.activation_mode == "wake_word" else "Всегда слушать")
        if self.settings_wake_words_var:
            self.settings_wake_words_var.set(", ".join(self.runtime.config.wake_words))
        if self.settings_wake_window_var:
            self.settings_wake_window_var.set(str(self.runtime.config.wake_window_sec))
        if self.settings_noise_gate_var:
            self.settings_noise_gate_var.set(int(self.runtime.config.voice_activation_threshold * 1000))
        if self.settings_status_var:
            self.settings_status_var.set("Список устройств обновлен.")

    def _current_audio_label(self, kind: str) -> str:
        options = self.settings_input_options if kind == "input" else self.settings_output_options
        current_index = self.runtime.config.input_device_index if kind == "input" else self.runtime.config.output_device_index
        for label, index in options.items():
            if index == current_index:
                return label
        return next(iter(options.keys()), "Авто")

    def _selected_audio_index(self, kind: str) -> int | None:
        if kind == "input" and self.settings_input_var:
            return self.settings_input_options.get(self.settings_input_var.get())
        if kind == "output" and self.settings_output_var:
            return self.settings_output_options.get(self.settings_output_var.get())
        return None

    def _start_microphone_test(self) -> None:
        self._stop_microphone_test()
        try:
            self.mic_test_monitor = core.AudioLevelMonitor(self._selected_audio_index("input"))
            self.mic_test_monitor.start()
            if self.settings_status_var:
                self.settings_status_var.set("Тест микрофона запущен. Говорите в микрофон.")
            self._poll_microphone_test()
        except Exception as error:
            if self.settings_status_var:
                self.settings_status_var.set(f"Не удалось запустить тест микрофона: {error}")

    def _poll_microphone_test(self) -> None:
        if not self.settings_window or not self.settings_window.winfo_exists() or not self.mic_test_monitor:
            return

        level = self.mic_test_monitor.get_level()
        self._render_microphone_meter(level)
        if self.mic_test_monitor.error and self.settings_status_var:
            self.settings_status_var.set(f"Ошибка теста микрофона: {self.mic_test_monitor.error}")
        self.root.after(60, self._poll_microphone_test)

    def _render_microphone_meter(self, level: float) -> None:
        if not self.mic_meter_canvas:
            return
        try:
            if not self.mic_meter_canvas.winfo_exists():
                return
        except tk.TclError:
            return

        active_bars = int(round(level * len(self.mic_meter_items)))
        for index, item in enumerate(self.mic_meter_items):
            if index < active_bars:
                color = "#3bb273" if index < 16 else "#d9a441" if index < 21 else "#d95d39"
                height = 8 + min(index, active_bars) * 0.9
                self.mic_meter_canvas.coords(item, 10 + index * 23, 34 - height, 26 + index * 23, 34)
            else:
                color = "#cfd8e3"
                self.mic_meter_canvas.coords(item, 10 + index * 23, 30, 26 + index * 23, 34)
            self.mic_meter_canvas.itemconfigure(item, fill=color)
        
    def _stop_microphone_test(self) -> None:
        if self.mic_test_monitor:
            self.mic_test_monitor.stop()
            self.mic_test_monitor = None
        if self.settings_window and self.settings_window.winfo_exists():
            self._render_microphone_meter(0.0)

    def _test_output_signal(self) -> None:
        try:
            label = core.play_output_test_tone(self._selected_audio_index("output"))
            if self.settings_status_var:
                self.settings_status_var.set(f"Тестовый сигнал отправлен на {label}.")
        except Exception as error:
            if self.settings_status_var:
                self.settings_status_var.set(f"Не удалось воспроизвести тестовый сигнал: {error}")

    def _test_output_speech(self) -> None:
        output_index = self._selected_audio_index("output")
        if self.settings_status_var:
            self.settings_status_var.set("Запускаю тест озвучки...")

        def worker() -> None:
            try:
                speaker = core.Speaker(
                    self.runtime.config.assistant_name,
                    output_index,
                    self.runtime.config.tts_voice,
                    self.runtime.config.piper_model_path,
                    self.runtime.config.piper_config_path,
                )
                speaker.speak("Проверка звука Гарфилда. Если вы меня слышите, значит вывод настроен правильно.")
                self.root.after(0, lambda: self.settings_status_var and self.settings_status_var.set("Тест озвучки завершен."))
            except Exception as error:
                error_message = f"Не удалось выполнить тест озвучки: {error}"
                self.root.after(
                    0,
                    lambda message=error_message: self.settings_status_var and self.settings_status_var.set(message),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _reload_skills(self) -> None:
        message = self.runtime.reload_skills()
        if self.settings_status_var:
            self.settings_status_var.set(message)
        self.status_var.set(message)

    def _open_skills_file(self) -> None:
        try:
            message = self.runtime.open_skills_file()
        except Exception as error:
            message = f"Не удалось открыть файл навыков: {error}"
        if self.settings_status_var:
            self.settings_status_var.set(message)
        self.status_var.set(message)

    def _apply_audio_settings(self) -> None:
        try:
            activation_mode = "wake_word" if self.settings_activation_var and self.settings_activation_var.get() == "По ключевой фразе" else "continuous"
            wake_words = []
            if self.settings_wake_words_var:
                wake_words = [part.strip() for part in self.settings_wake_words_var.get().split(",") if part.strip()]
            wake_window_sec = int(self.settings_wake_window_var.get()) if self.settings_wake_window_var and self.settings_wake_window_var.get().strip() else self.runtime.config.wake_window_sec
            voice_activation_threshold = (float(self.settings_noise_gate_var.get()) / 1000.0) if self.settings_noise_gate_var else self.runtime.config.voice_activation_threshold
            summary = self.runtime.apply_audio_settings(
                self._selected_audio_index("input"),
                self._selected_audio_index("output"),
                activation_mode=activation_mode,
                wake_words=wake_words,
                wake_window_sec=wake_window_sec,
                voice_activation_threshold=voice_activation_threshold,
            )
            save_config(self.runtime.config)
            if self.settings_status_var:
                self.settings_status_var.set(f"Настройки сохранены. {summary}")
            self.status_var.set(summary)
        except Exception as error:
            if self.settings_status_var:
                self.settings_status_var.set(f"Не удалось применить настройки: {error}")

    def _close_audio_settings(self) -> None:
        self._stop_microphone_test()
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.settings_window = None
        self.settings_status_var = None
        self.settings_input_var = None
        self.settings_output_var = None
        self.settings_activation_var = None
        self.settings_wake_words_var = None
        self.settings_wake_window_var = None
        self.settings_noise_gate_var = None
        self.settings_input_combo = None
        self.settings_output_combo = None
        self.settings_activation_combo = None
        self.mic_meter_canvas = None
        self.mic_meter_items = []

    def _shutdown_from_runtime(self) -> None:
        self._finalize_close()

    def _finalize_close(self) -> None:
        if self.is_closing:
            return
        self.is_closing = True
        self._close_audio_settings()
        self.runtime.stop()
        if self.root.winfo_exists():
            self.root.after(150, self.root.destroy)

    def on_close(self) -> None:
        if messagebox and not messagebox.askyesno("Выход", "Остановить Garfield Flagship?"):
            return
        self._finalize_close()


def choose_ui_mode(config: FlagshipConfig) -> str:
    if config.ui_mode == "gui":
        return "gui"
    if config.ui_mode == "console":
        return "console"
    return "gui" if tk is not None else "console"


def run_console(runtime: FlagshipRuntime) -> int:
    runtime.start()

    try:
        while not runtime.stop_event.is_set():
            for event in runtime.drain_events():
                timestamp = datetime.fromtimestamp(event.created_at).strftime("%H:%M:%S")
                print(f"{timestamp} | {event.kind.upper()}: {event.text}")

            if runtime.input_mode == "keyboard":
                runtime.submit_text(runtime.keyboard_input.read(), source="keyboard")
            else:
                time.sleep(0.2)
    except KeyboardInterrupt:
        runtime.stop()
        return 0

    for event in runtime.drain_events():
        timestamp = datetime.fromtimestamp(event.created_at).strftime("%H:%M:%S")
        print(f"{timestamp} | {event.kind.upper()}: {event.text}")

    return 0


def main() -> int:
    try:
        config = FlagshipConfig.load(CONFIG_PATH)
    except Exception as error:
        print(error)
        return 1

    setup_logging(config)
    logging.info("Запуск Garfield Flagship")
    runtime = FlagshipRuntime(config)
    ui_mode = choose_ui_mode(config)

    if ui_mode == "gui":
        try:
            from garfield_dashboard.app_shell import run_dashboard

            run_dashboard(
                runtime,
                save_config=save_config,
                base_dir=BASE_DIR,
                config_path=CONFIG_PATH,
                log_path=LOG_PATH,
                session_log_path=SESSION_LOG_PATH,
            )
            return 0
        except Exception as error:
            logging.warning("Modern dashboard недоступен, пробую legacy GUI: %s", error)

        try:
            app = FlagshipGUI(runtime)
            app.run()
            return 0
        except Exception as error:
            logging.warning("Legacy GUI недоступен, переключаюсь на console: %s", error)

    return run_console(runtime)


if __name__ == "__main__":
    raise SystemExit(main())
