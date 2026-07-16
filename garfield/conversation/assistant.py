from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections import OrderedDict
from contextlib import suppress
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from garfield_actions import ActionContext, create_default_registry
from garfield_actions.legacy_desktop import DesktopController
from garfield_config import clamp_int, load_json_config, resolve_config_path
from garfield_intents import (
    ActionRequest,
    Intent,
    IntentRouter,
    PendingAction,
    RiskLevel,
    confirmation_token,
    is_cancellation,
    is_confirmation,
    is_non_action_request,
    requires_confirmation,
)
from garfield_llm import (
    CacheEntry,
    LLMAuthenticationError,
    LLMEmptyResponseError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMResponseFormatError,
    LLMResult,
    build_answer_cache_key,
    is_cache_entry_valid,
    raise_for_llm_status,
    require_non_empty_string,
    validate_response_size,
)
from garfield_privacy import (
    SecretRedactingFilter,
    looks_sensitive,
    redact_sensitive_text,
)
from garfield_secrets import PROVIDERS, SecretStore, migrate_plaintext_secrets
from garfield_skills import SkillRegistry as SafeSkillRegistry

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    from piper.voice import PiperVoice
except ImportError:
    PiperVoice = None


BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "garfield_flagship_config.json"
LOG_PATH = BASE_DIR / "garfield_best.log"
SKILLS_PATH = BASE_DIR / "garfield_skills.json"


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
class AppConfig:
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
    ) -> "AppConfig":
        raw_data, load_warnings = load_json_config(path)
        if raw_data:
            if migrate_plaintext_secrets(
                raw_data,
                secret_store or SecretStore(),
            ):
                from garfield_io import atomic_write_text

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
        config.llm_provider = normalize_llm_provider(config.llm_provider)
        if not config.llm_model:
            config.llm_model = default_llm_model(config.llm_provider)
        config.llm_api_url = validate_llm_api_url(
            config.llm_provider,
            default_llm_api_url(
                config.llm_provider,
                config.llm_api_url,
            ),
            allow_custom=config.allow_custom_llm_endpoint,
        )
        config.activation_mode = config.activation_mode.lower().strip()
        if config.activation_mode not in {"continuous", "wake_word"}:
            config.activation_mode = "wake_word"
        if isinstance(config.wake_words, str):
            config.wake_words = [part.strip() for part in config.wake_words.split(",") if part.strip()]
        config.wake_words = [normalize_text(word) for word in config.wake_words if normalize_text(word)]
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
        if isinstance(config.confirm_phrases, str):
            config.confirm_phrases = [part.strip() for part in config.confirm_phrases.split(",") if part.strip()]
        if isinstance(config.cancel_phrases, str):
            config.cancel_phrases = [part.strip() for part in config.cancel_phrases.split(",") if part.strip()]
        config.confirm_phrases = [normalize_text(phrase) for phrase in config.confirm_phrases if normalize_text(phrase)]
        config.cancel_phrases = [normalize_text(phrase) for phrase in config.cancel_phrases if normalize_text(phrase)]
        if not config.confirm_phrases:
            config.confirm_phrases = ["да", "подтверждаю"]
        if not config.cancel_phrases:
            config.cancel_phrases = ["нет", "отмена", "отмени", "не надо"]
        return config


class HistoryPolicy(str, Enum):
    EXCLUDE = "exclude"
    INCLUDE = "include"
    INCLUDE_REDACTED = "include_redacted"


@dataclass
class AssistantReply:
    text: str
    should_exit: bool = False
    should_speak: bool = True
    history_policy: HistoryPolicy = HistoryPolicy.EXCLUDE
    sensitive: bool = False
    action_id: str | None = None


@dataclass
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: int
    is_default_input: bool = False
    is_default_output: bool = False


class ConversationHistory:
    def __init__(self, max_turns: int) -> None:
        self.max_turns = max_turns
        self.turns: list[tuple[str, str]] = []

    def add(self, user_text: str, assistant_text: str) -> None:
        self.turns.append((user_text, assistant_text))
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns :]

    def as_messages(self) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for user_text, assistant_text in self.turns:
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": assistant_text})
        return messages


def resolve_default_vosk_path() -> Path:
    candidates = (
        BASE_DIR / "models" / "vosk-model-ru-0.22",
        BASE_DIR / "vosk-model-ru-0.22",
        Path(r"C:\GARFILD\models\vosk-model-ru-0.22"),
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_default_piper_model_path() -> Path:
    return BASE_DIR / "models" / "piper" / "ru_RU-irina-medium.onnx"


def resolve_default_piper_config_path() -> Path:
    return BASE_DIR / "models" / "piper" / "ru_RU-irina-medium.onnx.json"


def resolve_piper_executable() -> str | None:
    candidates = [
        shutil.which("piper"),
        str(Path(sys.executable).with_name("Scripts").joinpath("piper.exe")),
        str(Path(sys.executable).parent.parent / "Scripts" / "piper.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


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


def setup_logging(config: AppConfig) -> None:
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


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _average_word_confidence(data: dict) -> float | None:
    words = data.get("result", [])
    if not isinstance(words, list) or not words:
        return None
    confidences = []
    for word in words:
        if not isinstance(word, dict):
            continue
        try:
            confidences.append(float(word.get("conf")))
        except (TypeError, ValueError):
            continue
    if not confidences:
        return None
    return sum(confidences) / len(confidences)


def require_sounddevice():
    try:
        import sounddevice as sd
    except ImportError as error:
        raise RuntimeError(
            "Не хватает sounddevice для работы со звуком. Установите зависимости командой uv sync."
        ) from error
    return sd


def _default_audio_indices(sd) -> tuple[int | None, int | None]:
    device_pair = getattr(sd.default, "device", None)
    if isinstance(device_pair, (list, tuple)) and len(device_pair) >= 2:
        input_index = int(device_pair[0]) if int(device_pair[0]) >= 0 else None
        output_index = int(device_pair[1]) if int(device_pair[1]) >= 0 else None
        return input_index, output_index
    return None, None


def list_audio_devices() -> list[AudioDevice]:
    sd = require_sounddevice()
    default_input, default_output = _default_audio_indices(sd)
    devices: list[AudioDevice] = []
    for index, raw_device in enumerate(sd.query_devices()):
        devices.append(
            AudioDevice(
                index=index,
                name=str(raw_device.get("name", f"Device {index}")).strip() or f"Device {index}",
                max_input_channels=int(raw_device.get("max_input_channels", 0) or 0),
                max_output_channels=int(raw_device.get("max_output_channels", 0) or 0),
                default_samplerate=int(raw_device.get("default_samplerate", 44100) or 44100),
                is_default_input=index == default_input,
                is_default_output=index == default_output,
            )
        )
    return devices


def get_audio_devices(kind: str) -> list[AudioDevice]:
    devices = list_audio_devices()
    if kind == "input":
        return [device for device in devices if device.max_input_channels > 0]
    if kind == "output":
        return [device for device in devices if device.max_output_channels > 0]
    raise ValueError(f"Unknown audio device kind: {kind}")


def resolve_audio_device(kind: str, preferred_index: int | None = None) -> AudioDevice | None:
    devices = get_audio_devices(kind)
    if not devices:
        return None

    if preferred_index is not None:
        for device in devices:
            if device.index == preferred_index:
                return device

    for device in devices:
        if kind == "input" and device.is_default_input:
            return device
        if kind == "output" and device.is_default_output:
            return device
    return devices[0]


def format_audio_device_label(device: AudioDevice, kind: str) -> str:
    tags: list[str] = []
    if kind == "input" and device.is_default_input:
        tags.append("по умолчанию")
    if kind == "output" and device.is_default_output:
        tags.append("по умолчанию")
    suffix = f" [{' / '.join(tags)}]" if tags else ""
    return f"{device.index}: {device.name}{suffix}"


def describe_audio_device(kind: str, preferred_index: int | None = None) -> str:
    device = resolve_audio_device(kind, preferred_index)
    if not device:
        return "не найдено"
    label = format_audio_device_label(device, kind)
    if preferred_index is None:
        return f"{label} [авто]"
    return label


class Speaker:
    def __init__(
        self,
        assistant_name: str,
        output_device_index: int | None = None,
        tts_voice: str = "ru-RU-SvetlanaNeural",
        piper_model_path: str = "",
        piper_config_path: str = "",
    ) -> None:
        self.assistant_name = assistant_name
        self.output_device_index = output_device_index
        self.tts_voice = tts_voice
        self.piper_model_path = piper_model_path or str(resolve_default_piper_model_path())
        self.piper_config_path = piper_config_path or str(resolve_default_piper_config_path())
        self.neural_tts_cooldown_until = 0.0
        self._piper_voice = None
        self._piper_load_failed = False
        self._piper_lock = threading.Lock()
        self._interrupt_event = threading.Event()

    def set_output_device(self, output_device_index: int | None) -> None:
        self.output_device_index = output_device_index

    def set_voice(self, tts_voice: str) -> None:
        self.tts_voice = tts_voice or "ru-RU-SvetlanaNeural"

    def interrupt(self) -> None:
        self._interrupt_event.set()
        try:
            require_sounddevice().stop()
        except Exception:
            pass

    def clear_interrupt(self) -> None:
        self._interrupt_event.clear()

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        self.clear_interrupt()

        logging.info("%s: %s", self.assistant_name, text)

        if self._prefers_edge_tts() and self._speak_with_edge_tts(text):
            return
        if self._speak_with_piper(text):
            return
        if not self._prefers_edge_tts() and self._speak_with_edge_tts(text):
            return
        if self._speak_with_selected_output(text):
            return
        if self._speak_with_pyttsx3(text):
            return
        if self._speak_with_windows_sapi(text):
            return

        print(f"{self.assistant_name}: {text}")

    def _prefers_edge_tts(self) -> bool:
        return self.tts_voice.strip().lower().endswith("neural")

    def warmup(self) -> None:
        try:
            self._get_piper_voice()
        except Exception as error:
            logging.debug("Не удалось прогреть TTS: %s", error)

    def _speak_with_piper(self, text: str) -> bool:
        model_path = Path(self.piper_model_path)
        config_path = Path(self.piper_config_path)
        if PiperVoice is None or not model_path.exists() or not config_path.exists():
            return False

        try:
            voice = self._get_piper_voice()
            if voice is None:
                return False
            self._play_piper_chunks(voice, text)
            return True
        except Exception as error:
            logging.warning("Piper офлайн-голос недоступен, переключаюсь на запасной TTS: %s", error)
            return False

    def _get_piper_voice(self):
        if self._piper_load_failed:
            return None
        if self._piper_voice is not None:
            return self._piper_voice

        with self._piper_lock:
            if self._piper_voice is not None:
                return self._piper_voice
            if self._piper_load_failed:
                return None

            try:
                self._piper_voice = PiperVoice.load(
                    model_path=Path(self.piper_model_path),
                    config_path=Path(self.piper_config_path),
                )
            except Exception as error:
                self._piper_load_failed = True
                logging.warning("Не удалось загрузить PiperVoice в память: %s", error)
                return None

            return self._piper_voice

    def _play_piper_chunks(self, voice, text: str) -> None:
        import numpy as np

        sd = require_sounddevice()
        output_device = resolve_audio_device("output", self.output_device_index)
        device_index = output_device.index if output_device is not None else None
        stream = None
        try:
            for chunk in voice.synthesize(text):
                if self._interrupt_event.is_set():
                    return
                audio = chunk.audio_float_array
                if audio is None or len(audio) == 0:
                    continue
                if audio.ndim == 1:
                    audio = audio.reshape(-1, 1)
                audio = np.asarray(audio, dtype=np.float32)

                if stream is None:
                    stream = sd.OutputStream(
                        samplerate=chunk.sample_rate,
                        channels=audio.shape[1],
                        dtype="float32",
                        device=device_index,
                        latency="low",
                    )
                    stream.start()

                block_size = max(512, min(4096, len(audio)))
                for start in range(0, len(audio), block_size):
                    if self._interrupt_event.is_set():
                        return
                    stream.write(audio[start : start + block_size])
        finally:
            if stream is not None:
                try:
                    stream.stop()
                finally:
                    stream.close()

    def _speak_with_edge_tts(self, text: str) -> bool:
        if edge_tts is None or shutil.which("ffmpeg") is None:
            return False
        if time.time() < self.neural_tts_cooldown_until:
            return False

        try:
            with tempfile.TemporaryDirectory(prefix="garfield_tts_") as temp_dir:
                if self._interrupt_event.is_set():
                    return False
                source_mp3 = os.path.join(temp_dir, "speech.mp3")
                rendered_wav = os.path.join(temp_dir, "speech.wav")
                asyncio.run(
                    edge_tts.Communicate(
                        text,
                        self.tts_voice,
                        rate="+0%",
                        pitch="+0Hz",
                        connect_timeout=4,
                        receive_timeout=15,
                    ).save(source_mp3)
                )
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        source_mp3,
                        rendered_wav,
                    ],
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                self._play_wav_file(rendered_wav)
                self.neural_tts_cooldown_until = 0.0
                return True
        except Exception as error:
            self.neural_tts_cooldown_until = time.time() + 300
            logging.warning("Neural TTS недоступен, переключаюсь на запасной голос: %s", error)
            return False

    def _speak_with_selected_output(self, text: str) -> bool:
        if platform.system() != "Windows":
            return False

        try:
            output_device = resolve_audio_device("output", self.output_device_index)
            if output_device is None:
                return False

            escaped_text = text.replace("'", "''")
            temp_path: str | None = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
                    temp_path = temp_file.name

                command = (
                    "[void][Reflection.Assembly]::LoadWithPartialName('System.Speech'); "
                    "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$speaker.SetOutputToWaveFile('{temp_path}'); "
                    f"$speaker.Speak('{escaped_text}'); "
                    "$speaker.Dispose()"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", command],
                    check=True,
                    capture_output=True,
                    timeout=45,
                )

                self._play_wav_file(temp_path)
                return True
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
        except Exception as error:
            logging.warning("Не удалось направить озвучку на выбранный выход: %s", error)
            return False

    def _play_wav_file(self, wav_path: str) -> None:
        import numpy as np

        sd = require_sounddevice()
        with wave.open(wav_path, "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            samplerate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())

        dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
        if sample_width not in dtype_map:
            raise RuntimeError(f"Неподдерживаемая глубина WAV: {sample_width}")

        audio = np.frombuffer(frames, dtype=dtype_map[sample_width]).astype(np.float32)
        audio /= float(2 ** (8 * sample_width - 1))
        if channels > 1:
            audio = audio.reshape(-1, channels)

        output_device = resolve_audio_device("output", self.output_device_index)
        device_index = output_device.index if output_device is not None else None
        stream = sd.OutputStream(
            samplerate=samplerate,
            channels=audio.shape[1] if audio.ndim > 1 else 1,
            dtype="float32",
            device=device_index,
            latency="low",
        )
        try:
            stream.start()
            block_size = max(1024, min(4096, len(audio)))
            for start in range(0, len(audio), block_size):
                if self._interrupt_event.is_set():
                    return
                stream.write(audio[start : start + block_size])
        finally:
            try:
                stream.stop()
            finally:
                stream.close()
            sd.stop()

    def _speak_with_pyttsx3(self, text: str) -> bool:
        if pyttsx3 is None:
            return False

        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 155)
            engine.setProperty("volume", 1.0)

            voice_id = self._find_russian_voice(engine)
            if voice_id:
                engine.setProperty("voice", voice_id)

            engine.say(text)
            engine.runAndWait()
            engine.stop()
            return True
        except Exception as error:
            logging.warning("PyTTSx3 недоступен: %s", error)
            return False

    def _find_russian_voice(self, engine: "pyttsx3.Engine") -> Optional[str]:
        try:
            for voice in engine.getProperty("voices"):
                voice_text = f"{getattr(voice, 'name', '')} {getattr(voice, 'id', '')}".lower()
                if "russian" in voice_text or "рус" in voice_text or "irina" in voice_text:
                    return voice.id
        except Exception as error:
            logging.debug("Не удалось выбрать русский голос: %s", error)
        return None

    def _speak_with_windows_sapi(self, text: str) -> bool:
        if platform.system() != "Windows":
            return False

        escaped = text.replace("'", "''")
        command = (
            "[void][Reflection.Assembly]::LoadWithPartialName('System.Speech'); "
            "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$speaker.Rate = -1; "
            "$voice = $speaker.GetInstalledVoices() | "
            "ForEach-Object { $_.VoiceInfo } | "
            "Where-Object { $_.Culture.Name -eq 'ru-RU' -and $_.Gender -eq 'Female' } | "
            "Select-Object -First 1; "
            "if ($voice) { $speaker.SelectVoice($voice.Name) }; "
            f"$speaker.Speak('{escaped}')"
        )

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                check=True,
                capture_output=True,
                timeout=30,
            )
            return True
        except Exception as error:
            logging.warning("Windows SAPI недоступен: %s", error)
            return False


class VoiceRecognizer:
    def __init__(self, model_path: Path, input_device_index: int | None = None) -> None:
        try:
            from vosk import KaldiRecognizer, Model
        except ImportError as error:
            raise RuntimeError(
                "Не хватает зависимостей для голосового режима. "
                "Установите зависимости командой uv sync."
            ) from error

        if not model_path.exists():
            raise FileNotFoundError(
                f"Модель Vosk не найдена: {model_path}. "
                "Исправьте путь в рабочем конфиге приложения."
            )

        self.sd = require_sounddevice()
        self.KaldiRecognizer = KaldiRecognizer
        self.model = Model(str(model_path))
        self.device = resolve_audio_device("input", input_device_index)
        if self.device is None:
            raise RuntimeError("Не найдено ни одного доступного устройства ввода.")
        self.sample_rate = self.device.default_samplerate if self.device.default_samplerate > 0 else 16000
        self._lock = threading.RLock()
        self._closed = False
        self._active_stream = None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            stream = self._active_stream
            self._active_stream = None
        if stream is not None:
            with suppress(Exception):
                stream.abort()
            with suppress(Exception):
                stream.close()

    def listen(
        self,
        timeout_sec: int,
        min_rms: float = 0.0,
        min_confidence: float = 0.0,
        silence_timeout_sec: float = 2.0,
        cancel_event: threading.Event | None = None,
    ) -> str:
        import numpy as np

        cancel_event = cancel_event or threading.Event()
        with self._lock:
            if self._closed:
                return ""

        recognizer = self.KaldiRecognizer(self.model, self.sample_rate)
        if hasattr(recognizer, "SetWords"):
            recognizer.SetWords(True)

        timeout_sec = max(1, int(timeout_sec or 1))
        silence_timeout_sec = max(0.2, float(silence_timeout_sec or 2.0))
        block_size = max(1024, int(self.sample_rate * 0.2))
        speech_started = min_rms <= 0
        last_voice_at = time.monotonic() if speech_started else 0.0
        started_at = time.monotonic()
        rms_values: list[float] = []
        chunks: list[bytes] = []
        prebuffer: list[bytes] = []
        max_prebuffer_blocks = max(1, int(0.6 / 0.2))

        stream = self.sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            device=self.device.index,
            blocksize=block_size,
        )
        with self._lock:
            if self._closed:
                with suppress(Exception):
                    stream.close()
                return ""
            self._active_stream = stream

        try:
            with stream:
                while (
                    not cancel_event.is_set()
                    and time.monotonic() - started_at < timeout_sec
                ):
                    block, _overflowed = stream.read(block_size)
                    if cancel_event.is_set():
                        break
                    block_bytes = block.tobytes()
                    audio = block.astype(np.float32) / 32768.0
                    rms = (
                        float(np.sqrt(np.mean(np.square(audio))))
                        if audio.size
                        else 0.0
                    )

                    has_voice = min_rms <= 0 or rms >= min_rms
                    if has_voice:
                        if not speech_started:
                            chunks.extend(prebuffer)
                            for buffered_block in prebuffer:
                                recognizer.AcceptWaveform(buffered_block)
                            prebuffer.clear()
                        speech_started = True
                        last_voice_at = time.monotonic()

                    if speech_started:
                        chunks.append(block_bytes)
                        recognizer.AcceptWaveform(block_bytes)
                        rms_values.append(rms)
                        if (
                            last_voice_at
                            and time.monotonic() - last_voice_at
                            >= silence_timeout_sec
                        ):
                            break
                    else:
                        prebuffer.append(block_bytes)
                        if len(prebuffer) > max_prebuffer_blocks:
                            prebuffer.pop(0)
        finally:
            with self._lock:
                if self._active_stream is stream:
                    self._active_stream = None

        if cancel_event.is_set() or not chunks:
            return ""

        rms = max(rms_values) if rms_values else 0.0
        if min_rms > 0 and rms < min_rms:
            return ""

        payload = recognizer.FinalResult()

        data = json.loads(payload)
        text = normalize_text(data.get("text", ""))
        if not text:
            return ""

        if min_confidence > 0:
            confidence = _average_word_confidence(data)
            if confidence is not None and confidence < min_confidence:
                logging.info("Команда отброшена: уверенность %.2f ниже порога %.2f.", confidence, min_confidence)
                return ""

        return text


class AudioLevelMonitor:
    def __init__(self, input_device_index: int | None = None) -> None:
        self.sd = require_sounddevice()
        self.device = resolve_audio_device("input", input_device_index)
        if self.device is None:
            raise RuntimeError("Не найдено ни одного доступного микрофона для теста.")
        self.level = 0.0
        self.error: str | None = None
        self.stream = None
        self._decay_lock = threading.Lock()

    def start(self) -> None:
        import numpy as np

        samplerate = self.device.default_samplerate if self.device.default_samplerate > 0 else 44100

        def callback(indata, frames, time_info, status) -> None:
            del frames, time_info
            if status:
                self.error = str(status)
            rms = float(np.sqrt(np.mean(np.square(indata.astype(np.float32)))))
            scaled = min(1.0, rms * 8.0)
            with self._decay_lock:
                self.level = max(scaled, self.level * 0.72)

        self.stream = self.sd.InputStream(
            device=self.device.index,
            channels=1,
            samplerate=samplerate,
            blocksize=max(256, int(samplerate * 0.05)),
            callback=callback,
        )
        self.stream.start()

    def stop(self) -> None:
        if self.stream is None:
            return
        try:
            self.stream.stop()
            self.stream.close()
        finally:
            self.stream = None

    def get_level(self) -> float:
        with self._decay_lock:
            level = self.level
            self.level *= 0.85
            return level


def play_output_test_tone(output_device_index: int | None = None, duration_sec: float = 1.2) -> str:
    import numpy as np

    sd = require_sounddevice()
    output_device = resolve_audio_device("output", output_device_index)
    if output_device is None:
        raise RuntimeError("Не найдено ни одного доступного устройства вывода.")

    samplerate = output_device.default_samplerate if output_device.default_samplerate > 0 else 44100
    times = np.linspace(0, duration_sec, int(samplerate * duration_sec), endpoint=False)
    tone = (
        0.18 * np.sin(2 * np.pi * 440 * times)
        + 0.12 * np.sin(2 * np.pi * 660 * times) * (times > duration_sec / 2)
    ).astype(np.float32)
    sd.play(tone, samplerate=samplerate, device=output_device.index, blocking=False)
    return format_audio_device_label(output_device, "output")


class KeyboardInput:
    def read(self) -> str:
        return self.listen(0)

    def listen(self, timeout_sec: int) -> str:
        del timeout_sec
        try:
            return normalize_text(input("Вы: "))
        except EOFError:
            return "выход"


LLM_PROVIDERS: dict[str, dict[str, object]] = {
    "nvidia": {
        "name": "NVIDIA",
        "api": "openai-completions",
        "chat_url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "api_key_env": "NVIDIA_API_KEY",
        "models": [
            {"id": "meta/llama-3.1-8b-instruct", "name": "Llama 3.1 8B Instruct"},
        ],
    },
    "openai": {
        "name": "OpenAI",
        "api": "openai-completions",
        "chat_url": "https://api.openai.com/v1/chat/completions",
        "api_key_env": "OPENAI_API_KEY",
        "models": [
            {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
        ],
    },
    "gemini": {
        "name": "Google Gemini",
        "api": "gemini-generate-content",
        "chat_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_key_env": "GEMINI_API_KEY",
        "models": [
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
            {"id": "gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash Lite"},
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
        ],
    },
    "groq": {
        "name": "Groq Cloud",
        "api": "openai-completions",
        "chat_url": "https://api.groq.com/openai/v1/chat/completions",
        "api_key_env": "GROQ_API_KEY",
        "models": [
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B Versatile"},
            {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B Instant"},
            {"id": "openai/gpt-oss-120b", "name": "GPT OSS 120B"},
            {"id": "openai/gpt-oss-20b", "name": "GPT OSS 20B"},
        ],
    },
    "xai": {
        "name": "Grok / xAI",
        "api": "openai-completions",
        "chat_url": "https://api.x.ai/v1/chat/completions",
        "api_key_env": "XAI_API_KEY",
        "models": [
            {"id": "grok-4.3", "name": "Grok 4.3"},
            {"id": "grok-4", "name": "Grok 4"},
        ],
    },
}


def normalize_llm_provider(provider: str) -> str:
    value = (provider or "").lower().strip()
    aliases = {
        "google": "gemini",
        "google_gemini": "gemini",
        "google-gemini": "gemini",
        "openai-chat": "openai",
        "grok": "xai",
        "x-ai": "xai",
    }
    value = aliases.get(value, value)
    return value if value in LLM_PROVIDERS else "nvidia"


def llm_provider_keys() -> list[str]:
    return list(LLM_PROVIDERS.keys())


def llm_model_ids(provider: str) -> list[str]:
    provider_key = normalize_llm_provider(provider)
    return [str(model["id"]) for model in LLM_PROVIDERS[provider_key]["models"]]  # type: ignore[index]


def default_llm_model(provider: str) -> str:
    ids = llm_model_ids(provider)
    return ids[0] if ids else ""


def describe_llm_provider(provider: str) -> str:
    provider_key = normalize_llm_provider(provider)
    return str(LLM_PROVIDERS[provider_key]["name"])


def default_llm_api_url(provider: str, current_url: str = "") -> str:
    provider_key = normalize_llm_provider(provider)
    default_url = str(LLM_PROVIDERS[provider_key]["chat_url"])
    if not current_url:
        return default_url

    known_urls = {str(info["chat_url"]) for info in LLM_PROVIDERS.values()}
    return default_url if current_url in known_urls else current_url


def validate_llm_api_url(
    provider: str,
    raw_url: str,
    *,
    allow_custom: bool,
) -> str:
    default_url = default_llm_api_url(provider, "")
    expected = urlparse(default_url)
    actual = urlparse(raw_url or default_url)
    if actual.scheme != "https":
        raise ValueError("LLM API должен использовать HTTPS.")
    if not actual.hostname:
        raise ValueError("LLM API URL не содержит hostname.")
    if actual.username or actual.password:
        raise ValueError("Логин и пароль внутри URL запрещены.")
    if not allow_custom and actual.hostname != expected.hostname:
        raise ValueError(
            "Для выбранного провайдера разрешён только стандартный API endpoint."
        )
    return actual.geturl()


def _config_api_key_env(config: object, provider: str) -> str:
    provider_key = normalize_llm_provider(provider)
    env_name = str(LLM_PROVIDERS[provider_key]["api_key_env"])
    return str(getattr(config, f"{provider_key}_api_key_env", env_name))


def create_llm_client(
    config: object,
    secret_store: SecretStore | None = None,
) -> "LLMClient | None":
    if not getattr(config, "use_llm", True):
        return None
    provider = normalize_llm_provider(getattr(config, "llm_provider", "nvidia"))
    model = getattr(config, "llm_model", "") or default_llm_model(provider)
    api_url = default_llm_api_url(provider, getattr(config, "llm_api_url", ""))
    api_key_env = _config_api_key_env(config, provider)
    return LLMClient(
        provider,
        api_url,
        model,
        api_key_env,
        secret_store=secret_store,
    )


class LLMClient:
    def __init__(
        self,
        provider: str,
        api_url: str,
        model: str,
        api_key_env: str,
        *,
        secret_store: SecretStore | None = None,
    ) -> None:
        self.provider = normalize_llm_provider(provider)
        self.api_url = default_llm_api_url(self.provider, api_url)
        self.model = model or default_llm_model(self.provider)
        self.api_key_env = api_key_env or str(LLM_PROVIDERS[self.provider]["api_key_env"])
        self.secret_store = secret_store or SecretStore()
        self.api_type = str(LLM_PROVIDERS[self.provider]["api"])
        self.session = requests.Session()

    def is_available(self) -> bool:
        try:
            return bool(self._stored_api_key())
        except Exception:
            return False

    def _api_key(self) -> str:
        key = self._stored_api_key()
        if not key:
            raise RuntimeError(
                f"Не задан ключ {describe_llm_provider(self.provider)} API. "
                f"Установите переменную окружения {self.api_key_env}."
            )
        return key

    def _stored_api_key(self) -> str:
        env_key = os.getenv(self.api_key_env, "").strip()
        if env_key:
            return env_key
        return self.secret_store.get(self.provider)

    def system_prompt(self, assistant_name: str) -> str:
        return (
            f"Ты {assistant_name}, надежный русскоязычный голосовой ассистент. "
            "Отвечай кратко, по делу и естественно. "
            "Не используй списки без необходимости."
        )

    def _messages(self, user_text: str, assistant_name: str, history: ConversationHistory) -> list[dict[str, str]]:
        messages = [
            {
                "role": "system",
                "content": self.system_prompt(assistant_name),
            }
        ]
        messages.extend(history.as_messages())
        messages.append({"role": "user", "content": user_text})
        return messages

    def ask(
        self,
        user_text: str,
        assistant_name: str,
        history: ConversationHistory,
        max_tokens: int = 450,
        timeout_sec: int = 18,
    ) -> LLMResult:
        messages = self._messages(user_text, assistant_name, history)
        try:
            if self.api_type == "gemini-generate-content":
                text = self._ask_gemini(
                    messages,
                    max_tokens=max_tokens,
                    timeout_sec=timeout_sec,
                )
            else:
                text = self._ask_openai_compatible(
                    messages,
                    max_tokens=max_tokens,
                    timeout_sec=timeout_sec,
                )
        except requests.RequestException as error:
            raise LLMNetworkError("Сетевая ошибка при обращении к LLM.") from error
        return LLMResult(text=text, provider=self.provider, model=self.model)

    def _ask_openai_compatible(self, messages: list[dict[str, str]], max_tokens: int, timeout_sec: int) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": 0.2,
            "top_p": 0.7,
            "max_tokens": max_tokens,
        }
        if self.provider == "groq" and self.model.startswith("openai/gpt-oss"):
            payload["reasoning_effort"] = "low"
            payload["max_tokens"] = max(max_tokens, 200)

        response = self.session.post(
            self.api_url,
            headers={
                "Authorization": f"Bearer {self._api_key()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=(5, timeout_sec),
        )
        raise_for_llm_status(response)
        validate_response_size(response)
        try:
            data = response.json()
            choices = data["choices"]
            content = choices[0]["message"]["content"]
        except (
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as error:
            raise LLMResponseFormatError(
                "LLM вернула ответ с неправильной структурой."
            ) from error
        return require_non_empty_string(content, "choices[0].message.content")

    def _ask_gemini(self, messages: list[dict[str, str]], max_tokens: int, timeout_sec: int) -> str:
        max_output_tokens = max(max_tokens, 128)
        system_parts: list[dict[str, str]] = []
        contents: list[dict[str, object]] = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if not content:
                continue
            if role == "system":
                system_parts.append({"text": content})
                continue
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": content}]})

        base_url = self.api_url.rstrip("/")
        if base_url.endswith(":generateContent"):
            url = base_url
        else:
            url = f"{base_url}/models/{self.model}:generateContent"

        response = self.session.post(
            url,
            params={"key": self._api_key()},
            headers={"Content-Type": "application/json"},
            json={
                "systemInstruction": {"parts": system_parts} if system_parts else None,
                "contents": contents,
                "generationConfig": {
                    "temperature": 0.2,
                    "topP": 0.7,
                    "maxOutputTokens": max_output_tokens,
                },
            },
            timeout=(5, timeout_sec),
        )
        raise_for_llm_status(response)
        validate_response_size(response)
        try:
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(
                require_non_empty_string(part["text"], "parts[].text")
                for part in parts
                if isinstance(part, dict)
            )
        except (
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as error:
            raise LLMResponseFormatError(
                "LLM вернула ответ с неправильной структурой."
            ) from error
        return require_non_empty_string(text, "candidates[0].content.parts")


class NVIDIAClient(LLMClient):
    def __init__(
        self,
        api_url: str,
        model: str,
        api_key_env: str,
        *,
        secret_store: SecretStore | None = None,
    ) -> None:
        super().__init__(
            "nvidia",
            api_url,
            model,
            api_key_env,
            secret_store=secret_store,
        )


COMMAND_CATALOG: list[tuple[str, list[str]]] = [
    (
        "Голос и режимы",
        [
            "включи прослушивание",
            "выключи прослушивание",
            "включи режим по ключевой фразе",
            "включи непрерывный режим",
            "какая ключевая фраза",
            "стоп ответ / замолчи",
        ],
    ),
    (
        "Мышь и клавиатура",
        [
            "клик / правый клик / двойной клик",
            "курсор вверх / вниз / влево / вправо",
            "скролл вверх / скролл вниз",
            "напечатай <текст>",
            "копировать / вставить / выделить всё",
            "удали последнее слово / удали весь текст",
        ],
    ),
    (
        "Окна и Windows",
        [
            "сверни окно / сверни все окна",
            "разверни окно / переключи окно / закрой окно",
            "заблокируй экран",
            "очисти корзину",
            "выключи компьютер / перезагрузи компьютер / спящий режим",
        ],
    ),
    (
        "Браузер и сайты",
        [
            "открой браузер / открой YouTube / открой VK / открой почту",
            "найди <запрос>",
            "найди картинки <запрос>",
            "новая вкладка / закрой вкладку / верни вкладку",
            "следующая вкладка / предыдущая вкладка",
            "обнови страницу / открой загрузки / добавь в закладки",
        ],
    ),
    (
        "Звук и экран",
        [
            "громкость 50 процентов",
            "громче / тише / без звука",
            "яркость 70 процентов",
        ],
    ),
    (
        "Документы и текст",
        [
            "сохрани как",
            "в начало / в конец / начало строки / конец строки",
            "по левому краю / по центру / по правому краю / по ширине",
            "отправь сообщение",
            "отмени действие",
        ],
    ),
    (
        "Навыки и сервис",
        [
            "список команд",
            "покажи навыки",
            "обнови навыки",
            "очисти память",
            "очисти кэш",
            "сохрани диалог",
        ],
    ),
]


def command_catalog() -> list[tuple[str, list[str]]]:
    return [(title, list(commands)) for title, commands in COMMAND_CATALOG]


class AssistantCore:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.history = ConversationHistory(config.remember_turns)
        self.desktop = DesktopController(config.allow_power_commands)
        self.action_context = ActionContext(
            platform_name=platform.system(),
            desktop_enabled=config.enable_desktop_commands,
            power_enabled=config.allow_power_commands,
            metadata={
                "clipboard_writer": self.desktop._set_clipboard_text,
                "desktop_controller": self.desktop,
                "project_root": BASE_DIR,
            },
        )
        self.actions = create_default_registry(self.action_context)
        self.llm_client = create_llm_client(config)
        self.pending_action: PendingAction | None = None
        self.last_answer = ""
        self.last_user_command = ""
        self.previous_user_command = ""
        self.answer_cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.skills = SafeSkillRegistry(
            Path(config.skills_path),
            self.actions,
            project_root=BASE_DIR,
        )
        self.intent_router = IntentRouter()

    def handle(self, raw_text: str) -> Optional[AssistantReply]:
        text = normalize_text(raw_text)
        if not text:
            return None

        self.previous_user_command = self.last_user_command
        self.last_user_command = text

        if self.config.require_name_prefix and not self._is_addressed_to_assistant(text):
            return None

        reply = self._dispatch(text)
        if reply is None:
            return None

        self.last_answer = reply.text
        self._remember_reply(text, reply)
        return reply

    def _dispatch(self, text: str) -> AssistantReply | None:
        if self.pending_action:
            reply = self._handle_pending_action(text)
            if reply:
                return reply

        intent = self.intent_router.route(text)
        if intent is not None:
            return self._handle_intent(intent)

        builtin_reply = self._handle_builtin_command(text)
        if builtin_reply:
            return builtin_reply

        skill_reply = self._handle_skill(text)
        if skill_reply:
            return skill_reply

        answer = self._ask_llm_or_fallback(text)
        sensitive = looks_sensitive(text)
        return AssistantReply(
            text=answer,
            history_policy=(
                HistoryPolicy.INCLUDE_REDACTED
                if sensitive
                else HistoryPolicy.INCLUDE
            ),
            sensitive=sensitive,
        )

    def _handle_intent(self, intent: Intent) -> AssistantReply:
        return self._execute_registered_action(intent.intent_id, intent.arguments)

    def _execute_registered_action(
        self,
        action_id: str,
        arguments: dict[str, object] | None = None,
    ) -> AssistantReply:
        arguments = dict(arguments or {})
        try:
            definition = self.actions.validate(action_id, arguments)
        except ValueError:
            return AssistantReply("Команда пока не поддерживается.", should_speak=False)

        request = ActionRequest(
            action_id=action_id,
            arguments=arguments,
            risk=definition.risk,
            display_name=definition.display_name,
        )
        if definition.risk is RiskLevel.SYSTEM and not self.config.allow_power_commands:
            return AssistantReply("Системные команды сейчас отключены в конфигурации.")
        if requires_confirmation(request):
            token = confirmation_token(action_id)
            self.pending_action = PendingAction(
                request=request,
                created_at=time.monotonic(),
                confirmation_token=token,
            )
            return AssistantReply(
                f"Подтвердите действие: {token}.",
                action_id=action_id,
            )

        result = self.actions.execute(action_id, arguments)
        return AssistantReply(
            result.message,
            should_speak=result.success,
            sensitive=bool(definition.sensitive_arguments),
            action_id=action_id,
        )

    def _remember_reply(self, user_text: str, reply: AssistantReply) -> None:
        if not reply.text or reply.history_policy is HistoryPolicy.EXCLUDE:
            return

        if reply.history_policy is HistoryPolicy.INCLUDE_REDACTED:
            known_secrets = self._known_secrets()
            user_text = redact_sensitive_text(user_text, known_secrets)
            assistant_text = redact_sensitive_text(reply.text, known_secrets)
        else:
            assistant_text = reply.text

        self.history.add(user_text, assistant_text)

    def _known_secrets(self) -> list[str]:
        secrets: list[str] = []
        for provider in ("nvidia", "openai", "gemini", "groq", "xai"):
            env_name = str(getattr(self.config, f"{provider}_api_key_env", "")).strip()
            if env_name:
                env_key = os.getenv(env_name, "").strip()
                if env_key:
                    secrets.append(env_key)
            client = self.llm_client
            if client and getattr(client, "provider", "") == provider:
                try:
                    stored_key = client.secret_store.get(provider).strip()
                except Exception:
                    stored_key = ""
                if stored_key:
                    secrets.append(stored_key)
        return secrets

    def _is_addressed_to_assistant(self, text: str) -> bool:
        return self.config.assistant_name.lower() in text

    def _handle_pending_action(self, text: str) -> AssistantReply | None:
        if self.pending_action is None:
            return None

        timeout_sec = getattr(self.config, "command_confirmation_timeout_sec", 20)
        pending = self.pending_action
        if pending.is_expired(timeout_sec):
            self.pending_action = None
            return AssistantReply("Время подтверждения истекло. Команда отменена.")

        cancel_phrases = getattr(self.config, "cancel_phrases", ["нет", "отмена", "отмени", "не надо"])
        if is_cancellation(text, cancel_phrases):
            self.pending_action = None
            return AssistantReply("Команда отменена.")

        confirm_phrases = getattr(self.config, "confirm_phrases", ["да", "подтверждаю"])
        if is_confirmation(text, pending, confirm_phrases):
            self.pending_action = None
            return self._execute_pending_action(pending.request)

        if normalize_text(text) in {normalize_text(phrase) for phrase in confirm_phrases}:
            return AssistantReply(
                (
                    f"Для подтверждения скажите «{confirm_phrases[-1]} "
                    f"{pending.confirmation_token}» или «{cancel_phrases[0]}»."
                )
            )

        self.pending_action = None
        return None

    def _execute_pending_action(self, request: ActionRequest) -> AssistantReply:
        try:
            result = self.actions.execute(request.action_id, request.arguments)
        except ValueError:
            return AssistantReply(
                "Неизвестное подтверждённое действие.",
                should_speak=False,
            )
        return AssistantReply(
            result.message,
            should_speak=result.success,
            action_id=request.action_id,
        )

    def _power_action_label(self, kind: str) -> str:
        return {
            "shutdown": "выключение",
            "restart": "перезагрузку",
            "sleep": "спящий режим",
        }.get(kind, "действие")

    def _desktop_unavailable(self) -> Optional[AssistantReply]:
        if self.config.enable_desktop_commands:
            return None
        return AssistantReply("Desktop-команды отключены в конфиге.")

    def _extract_percent(self, text: str) -> int | None:
        if "максимум" in text or "на полную" in text:
            return 100
        if "половин" in text:
            return 50
        match = re.search(r"(\d{1,3})\s*(?:%|процент|процента|процентов)?", text)
        if not match:
            return None
        return max(0, min(int(match.group(1)), 100))

    def _command_catalog_text(self) -> str:
        chunks = []
        for title, commands in command_catalog():
            chunks.append(f"{title}: " + "; ".join(commands))
        return "\n".join(chunks)

    def _handle_builtin_command(self, text: str) -> Optional[AssistantReply]:
        if is_non_action_request(text):
            return None

        if contains_any(text, ("остановись", "выход", "стоп", "пока", "заверши")):
            return AssistantReply("Завершаю работу. До свидания.", should_exit=True)

        if contains_any(text, ("помощь", "что ты умеешь", "твои возможности", "расскажи о себе")):
            return AssistantReply(self._help_text())

        if contains_any(text, ("который час", "сколько времени", "текущее время", "время")):
            return AssistantReply(f"Сейчас {datetime.now():%H:%M}.")

        if contains_any(text, ("какая сегодня дата", "какое сегодня число", "сегодняшняя дата", "дата")):
            return AssistantReply(f"Сегодня {datetime.now():%d.%m.%Y}.")

        if contains_any(text, ("повтори ответ", "повтори", "скажи еще раз")):
            if self.last_answer:
                return AssistantReply(self.last_answer)
            return AssistantReply("Пока мне нечего повторять.")

        if contains_any(text, ("что ты услышал", "какую команду ты услышал")):
            heard_text = self.previous_user_command or self.last_user_command
            return AssistantReply(f"Я услышал: {heard_text}.")

        if contains_any(text, ("список команд", "покажи команды", "команды программы", "что умеет программа")):
            return AssistantReply(self._command_catalog_text(), should_speak=False)

        if text.startswith(("напечатай ", "введи текст ", "набери текст ")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            for prefix in ("напечатай ", "введи текст ", "набери текст "):
                if text.startswith(prefix):
                    return self._execute_registered_action("text.type", {"text": text.removeprefix(prefix).strip()})

        if contains_any(text, ("копируй", "копировать", "скопируй текст")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("text.copy")

        if contains_any(text, ("вырежи", "вырезать")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("text.cut")

        if contains_any(text, ("вставь", "вставить")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("text.paste")

        if contains_any(text, ("выдели всё", "выдели все", "выделить всё", "выделить все")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("text.select_all")

        if contains_any(text, ("удали последнее слово", "стереть последнее слово")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("text.delete_last_word")

        if contains_any(text, ("удали весь текст", "очисти текст", "стереть весь текст")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("text.delete_all")

        if contains_any(text, ("отправь сообщение", "отправить сообщение", "нажми enter", "нажми энтер")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("message.send")

        if contains_any(text, ("отмени действие", "отмена последнего действия", "undo")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("text.undo")

        if contains_any(text, ("сохрани как", "сохранить как")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("text.save_as")

        text_navigation = {
            ("в начало документа", "перейди в начало документа", "в самое начало"): "document_start",
            ("в конец документа", "перейди в конец документа", "в самый конец"): "document_end",
            ("в начало строки", "начало строки"): "line_start",
            ("в конец строки", "конец строки"): "line_end",
            ("курсор вверх", "строкой выше"): "up",
            ("курсор вниз", "строкой ниже"): "down",
            ("курсор влево", "символ влево"): "left",
            ("курсор вправо", "символ вправо"): "right",
        }
        for phrases, action in text_navigation.items():
            if contains_any(text, phrases):
                disabled = self._desktop_unavailable()
                if disabled:
                    return disabled
                return self._execute_registered_action("text.navigate", {"action": action})

        alignment_commands = {
            ("по левому краю", "выравнивание влево"): "align_left",
            ("по центру", "выровняй по центру"): "align_center",
            ("по правому краю", "выравнивание вправо"): "align_right",
            ("по ширине", "выровняй по ширине"): "align_justify",
        }
        for phrases, action in alignment_commands.items():
            if contains_any(text, phrases):
                disabled = self._desktop_unavailable()
                if disabled:
                    return disabled
                return self._execute_registered_action("text.format", {"action": action})

        if contains_any(text, ("смени язык", "переключи язык", "смена языка ввода")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("input_language.switch")

        if contains_any(text, ("открой браузер", "открой хром", "запусти браузер")):
            return self._execute_registered_action("web.open", {"url": "https://www.google.com"})

        if contains_any(text, ("открой ютуб", "открой youtube", "запусти ютуб")):
            return self._execute_registered_action("web.open", {"url": "https://www.youtube.com"})

        site_commands = {
            ("открой вк", "открой вконтакте", "запусти вк"): ("ВКонтакте", "https://vk.com"),
            ("открой почту", "открой mail", "открой мэйл"): ("почту Mail", "https://mail.ru"),
            ("открой netflix", "открой нетфликс"): ("Netflix", "https://www.netflix.com"),
            ("открой telegram", "открой телеграм"): ("Telegram Web", "https://web.telegram.org"),
        }
        for phrases, (_label, url) in site_commands.items():
            if contains_any(text, phrases):
                return self._execute_registered_action("web.open", {"url": url})

        browser_commands = {
            ("новая вкладка", "открой вкладку", "создай вкладку"): "new_tab",
            ("закрой вкладку", "закрыть вкладку"): "close_tab",
            ("верни вкладку", "восстанови вкладку", "вернуть вкладку"): "restore_tab",
            ("следующая вкладка", "перейди на следующую вкладку"): "next_tab",
            ("предыдущая вкладка", "прошлая вкладка"): "previous_tab",
            ("обнови страницу", "перезагрузи страницу"): "refresh",
            ("открой загрузки", "покажи загрузки"): "downloads",
            ("открой историю браузера", "покажи историю браузера"): "history",
            ("открой закладки", "покажи закладки"): "bookmarks",
            ("добавь в закладки", "добавить в закладки"): "add_bookmark",
            ("поиск по странице", "найди на странице"): "find_page",
            ("адресная строка", "перейди в адресную строку"): "address_bar",
            ("очисти историю браузера", "удали историю браузера"): "clear_history",
        }
        for phrases, action in browser_commands.items():
            if contains_any(text, phrases):
                disabled = self._desktop_unavailable()
                if disabled:
                    return disabled
                return self._execute_registered_action("browser.shortcut", {"action": action})

        if text.startswith(("найди картинки ", "поиск картинок ", "найди изображения ")):
            for prefix in ("найди картинки ", "поиск картинок ", "найди изображения "):
                if text.startswith(prefix):
                    query = text.removeprefix(prefix).strip()
                    if query:
                        return self._execute_registered_action("image.search", {"query": query})

        if contains_any(text, ("сверни все окна", "свернуть все окна")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("window.minimize_all")

        if contains_any(text, ("сверни окно", "свернуть окно", "сверни текущее окно")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("window.minimize")

        if contains_any(text, ("разверни окно", "развернуть окно", "восстанови окно")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("window.maximize")

        if contains_any(text, ("переключи окно", "следующее окно", "другое окно")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("window.switch")

        if contains_any(text, ("закрой окно", "закрой приложение")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("window.close")

        mouse_commands = {
            ("левый клик", "кликни", "нажми левую кнопку мыши"): ("click", "left"),
            ("правый клик", "нажми правую кнопку мыши"): ("click", "right"),
            ("двойной клик", "дважды кликни"): ("double", ""),
            ("мышь влево", "курсор мыши влево"): ("move", "left"),
            ("мышь вправо", "курсор мыши вправо"): ("move", "right"),
            ("мышь вверх", "курсор мыши вверх"): ("move", "up"),
            ("мышь вниз", "курсор мыши вниз"): ("move", "down"),
            ("скролл вверх", "прокрути вверх", "прокрутка вверх"): ("scroll", "up"),
            ("скролл вниз", "прокрути вниз", "прокрутка вниз"): ("scroll", "down"),
        }
        for phrases, (action, value) in mouse_commands.items():
            if contains_any(text, phrases):
                disabled = self._desktop_unavailable()
                if disabled:
                    return disabled
                if action == "click":
                    return self._execute_registered_action("mouse.click", {"button": value})
                if action == "double":
                    return self._execute_registered_action("mouse.double_click")
                if action == "move":
                    return self._execute_registered_action("mouse.move", {"direction": value})
                if action == "scroll":
                    return self._execute_registered_action("mouse.scroll", {"direction": value})

        if contains_any(text, ("громкость", "звук")):
            percent = self._extract_percent(text)
            if percent is not None and contains_any(text, ("громкость", "звук", "поставь звук", "установи звук")):
                disabled = self._desktop_unavailable()
                if disabled:
                    return disabled
                return self._execute_registered_action("volume.set", {"percent": percent})

        if contains_any(text, ("без звука", "выключи звук", "выключи системный звук", "заглуши звук", "mute")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("volume.mute")

        if contains_any(text, ("включи звук", "включи системный звук")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("volume.step", {"direction": "up", "presses": 1})

        if contains_any(text, ("сделай громче", "громче", "увеличь громкость")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("volume.step", {"direction": "up"})

        if contains_any(text, ("сделай тише", "тише", "уменьши громкость")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("volume.step", {"direction": "down"})

        if contains_any(text, ("яркость", "подсветка")):
            percent = self._extract_percent(text)
            if percent is not None:
                disabled = self._desktop_unavailable()
                if disabled:
                    return disabled
                return self._execute_registered_action("brightness.set", {"percent": percent})

        if contains_any(text, ("очисти корзину", "очистить корзину")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("recycle_bin.empty")

        if contains_any(text, ("заблокируй экран", "блокировка экрана", "заблокировать компьютер")):
            disabled = self._desktop_unavailable()
            if disabled:
                return disabled
            return self._execute_registered_action("screen.lock")

        if contains_any(text, ("отмени выключение", "отмени перезагрузку", "отмена выключения")):
            return self._execute_registered_action("system.cancel_power_timer")

        if text.startswith("найди "):
            query = text.removeprefix("найди ").strip()
            if query:
                return self._execute_registered_action("web.search", {"query": query})

        if text.startswith("поиск "):
            query = text.removeprefix("поиск ").strip()
            if query:
                return self._execute_registered_action("web.search", {"query": query})

        if contains_any(text, ("выключи компьютер", "выключение компьютера")):
            if not self.config.allow_power_commands:
                return AssistantReply("Силовые команды сейчас отключены в конфиге ради безопасности.")
            return self._handle_intent(
                Intent("system.shutdown", risk=RiskLevel.SYSTEM, original_text=text)
            )

        if contains_any(text, ("перезагрузи компьютер", "перезагрузка компьютера")):
            if not self.config.allow_power_commands:
                return AssistantReply("Силовые команды сейчас отключены в конфиге ради безопасности.")
            return self._handle_intent(
                Intent("system.restart", risk=RiskLevel.SYSTEM, original_text=text)
            )

        if contains_any(text, ("спящий режим", "переведи в сон", "усыпи компьютер", "сон компьютера")):
            if not self.config.allow_power_commands:
                return AssistantReply("Силовые команды сейчас отключены в конфиге ради безопасности.")
            return self._handle_intent(
                Intent("system.sleep", risk=RiskLevel.SYSTEM, original_text=text)
            )

        if contains_any(text, ("обнови навыки", "перезагрузи навыки", "reload skills")):
            count, error = self.skills.reload()
            if error:
                return AssistantReply(f"Не удалось загрузить навыки: {error}", should_speak=False)
            return AssistantReply(f"Навыки обновлены. Активно {count}.", should_speak=False)

        if contains_any(text, ("список навыков", "покажи навыки", "какие навыки доступны")):
            return AssistantReply(self.skills.describe(), should_speak=False)

        return None

    def _power_confirmation_text(self, label: str) -> str:
        if not self.config.allow_power_commands:
            return "Силовые команды сейчас отключены в конфиге ради безопасности."
        confirm = getattr(self.config, "confirm_phrases", ["да", "подтверждаю"])[0]
        cancel = getattr(self.config, "cancel_phrases", ["нет", "отмена"])[0]
        timeout = getattr(self.config, "command_confirmation_timeout_sec", 20)
        return (
            f"Подтвердите {label}. "
            f"Скажите {confirm} или {cancel}. Автоотмена через {timeout} секунд."
        )

    def _handle_skill(self, text: str) -> Optional[AssistantReply]:
        match = self.skills.match(text)
        if match is None:
            return None
        try:
            return AssistantReply(self.skills.execute(match))
        except Exception as error:
            logging.warning("Ошибка навыка %s: %s", match.skill.skill_id, error)
            return AssistantReply(f"Не удалось выполнить навык {match.skill.skill_id}: {error}", should_speak=False)

    def _help_text(self) -> str:
        desktop_text = (
            "Также умею управлять браузером, вкладками, окнами, мышью, текстом, "
            "громкостью, яркостью и быстрыми сайтами."
            if self.config.enable_desktop_commands
            else "Desktop-команды отключены в конфиге."
        )
        power_text = (
            "Команды выключения, перезагрузки и сна доступны только через подтверждение."
            if self.config.allow_power_commands
            else "Команды выключения и перезагрузки сейчас отключены."
        )
        return (
            "Я умею поддерживать диалог, отвечать через выбранный ИИ-провайдер, "
            "говорить время и дату, повторять последний ответ. "
            f"{desktop_text} {power_text} Для полного списка скажите список команд."
        )

    def _ask_llm_or_fallback(self, text: str) -> str:
        sensitive = looks_sensitive(text)
        if self.llm_client and self.llm_client.is_available():
            cache_key = build_answer_cache_key(
                provider=self.llm_client.provider,
                model=self.llm_client.model,
                system_prompt=self.llm_client.system_prompt(
                    self.config.assistant_name
                ),
                history=self.history.as_messages(),
                user_text=text,
            )
            entry = self.answer_cache.get(cache_key)
            if (
                not sensitive
                and entry
                and is_cache_entry_valid(
                    entry,
                    self.config.answer_cache_ttl_sec,
                )
            ):
                self.answer_cache.move_to_end(cache_key)
                return entry.answer
            if entry:
                self.answer_cache.pop(cache_key, None)

            try:
                result = self.llm_client.ask(
                    text,
                    self.config.assistant_name,
                    self.history,
                )
                if not sensitive:
                    self._remember_answer(cache_key, result.text)
                return result.text
            except LLMAuthenticationError:
                logging.warning("LLM отклонила учётные данные.")
            except LLMRateLimitError:
                logging.warning("Достигнут лимит запросов к LLM.")
            except LLMEmptyResponseError:
                logging.warning("LLM вернула пустой ответ.")
            except LLMResponseFormatError:
                logging.warning("LLM вернула ответ неправильной структуры.")
            except LLMNetworkError:
                logging.warning("LLM временно недоступна из-за сетевой ошибки.")

        return self._fallback_answer(text)

    def _remember_answer(self, cache_key: str, answer: str) -> None:
        self.answer_cache[cache_key] = CacheEntry(
            answer=answer,
            created_at=time.monotonic(),
        )
        self.answer_cache.move_to_end(cache_key)
        while len(self.answer_cache) > self.config.max_cached_answers:
            self.answer_cache.popitem(last=False)

    def _fallback_answer(self, text: str) -> str:
        if "привет" in text:
            return f"Привет. Я {self.config.assistant_name}. Чем помочь?"
        if "как дела" in text:
            return "Работаю стабильно. Готов помочь."
        if "спасибо" in text:
            return "Пожалуйста."
        if "кто ты" in text:
            return f"Я {self.config.assistant_name}, основная версия голосового ассистента."
        if "что нового" in text:
            return "Сейчас я работаю в локальном режиме и готов выполнять базовые команды."
        return (
            "Не уверен в ответе. Попробуйте переформулировать вопрос "
            "или проверьте доступность выбранного ИИ-провайдера."
        )

def create_input_source(config: AppConfig) -> tuple[object, str]:
    if config.input_mode == "keyboard":
        return KeyboardInput(), "keyboard"

    try:
        recognizer = VoiceRecognizer(Path(config.vosk_model_path))
        return recognizer, "voice"
    except Exception as error:
        if config.input_mode == "voice":
            raise
        logging.warning("Голосовой режим недоступен, переключаюсь на keyboard: %s", error)
        return KeyboardInput(), "keyboard"


def main() -> int:
    try:
        config = AppConfig.load(CONFIG_PATH)
    except Exception as error:
        print(error)
        return 1

    setup_logging(config)
    logging.info("Запуск Garfield BEST")
    speaker = Speaker(
        config.assistant_name,
        config.output_device_index,
        config.tts_voice,
        config.piper_model_path,
        config.piper_config_path,
    )
    speaker.warmup()
    assistant = AssistantCore(config)

    try:
        input_source, source_name = create_input_source(config)
    except Exception as error:
        logging.error("%s", error)
        print(error)
        return 1

    startup_message = (
        f"{config.assistant_name} готов к работе. "
        f"Режим ввода: {source_name}. "
        "Скажите помощь, чтобы узнать возможности."
    )
    speaker.speak(startup_message)

    while True:
        try:
            logging.info("Ожидаю ввод...")
            if isinstance(input_source, VoiceRecognizer):
                text = input_source.listen(
                    config.recognition_timeout_sec,
                    min_confidence=config.recognition_confidence_threshold,
                )
            else:
                text = input_source.listen(config.recognition_timeout_sec)
        except KeyboardInterrupt:
            speaker.speak("Останавливаюсь по запросу пользователя.")
            return 0
        except Exception as error:
            logging.error("Ошибка получения ввода: %s", error)
            time.sleep(1)
            continue

        if not text:
            logging.info("Пустой ввод или речь не распознана.")
            continue

        logging.info(
            "Получена пользовательская команда%s.",
            " с чувствительными данными" if looks_sensitive(text) else "",
        )
        reply = assistant.handle(text)
        if reply is None:
            logging.info("Команда проигнорирована.")
            continue

        if reply.should_speak and reply.text:
            speaker.speak(reply.text)
        elif reply.text:
            print(reply.text)

        if reply.should_exit:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
