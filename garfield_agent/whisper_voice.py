"""Optional Whisper speech recognition, independent of the default Vosk engine.

Requires: pip install faster-whisper. Model files may download on first use.
"""
from __future__ import annotations

import logging
import math
import time

from garfield_best import normalize_text, require_sounddevice, resolve_audio_device


class WhisperRecognizer:
    def __init__(self, model_name: str = "base", input_device_index: int | None = None):
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError("Для режима Whisper выполните pip install faster-whisper") from error
        if model_name not in {"tiny", "base", "small", "medium"}:
            raise ValueError("Модель Whisper должна быть tiny, base, small или medium")
        self.sd = require_sounddevice()
        self.device = resolve_audio_device("input", input_device_index)
        if self.device is None:
            raise RuntimeError("Микрофон не найден")
        self.sample_rate = int(self.device.default_samplerate or 16000)
        self.model = WhisperModel(model_name, device="auto", compute_type="int8")

    def listen(
        self,
        timeout_sec: int,
        min_rms: float = 0.0,
        min_confidence: float = 0.0,
        silence_timeout_sec: float = 2.0,
    ) -> str:
        import numpy as np

        block_size = max(512, int(self.sample_rate * 0.2))
        timeout_sec = max(1, int(timeout_sec))
        silence_timeout_sec = max(0.4, float(silence_timeout_sec))
        started_at = time.monotonic()
        last_voice = 0.0
        heard_voice = False
        frames: list[np.ndarray] = []
        prebuffer: list[np.ndarray] = []

        with self.sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32",
            device=self.device.index, blocksize=block_size,
        ) as stream:
            while time.monotonic() - started_at < timeout_sec:
                data, overflow = stream.read(block_size)
                if overflow:
                    logging.debug("Whisper: аудиопоток переполнен")
                block = data[:, 0].copy()
                rms = float(np.sqrt(np.mean(block * block))) if block.size else 0.0
                active = rms >= max(min_rms, 0.001)
                if active:
                    if not heard_voice:
                        frames.extend(prebuffer)
                    heard_voice = True
                    last_voice = time.monotonic()
                if heard_voice:
                    frames.append(block)
                    if last_voice and time.monotonic() - last_voice >= silence_timeout_sec:
                        break
                else:
                    prebuffer.append(block)
                    if len(prebuffer) > 3:
                        prebuffer.pop(0)

        if not frames or not heard_voice:
            return ""
        audio = np.concatenate(frames).astype(np.float32)
        # faster-whisper consumes 16 kHz audio. Avoid extra heavy resampler dependency.
        if self.sample_rate != 16000:
            length = max(1, round(audio.size * 16000 / self.sample_rate))
            audio = np.interp(
                np.linspace(0, audio.size - 1, length),
                np.arange(audio.size), audio,
            ).astype(np.float32)

        segments, _info = self.model.transcribe(
            audio, language="ru", beam_size=1,
            vad_filter=True, condition_on_previous_text=False,
        )
        accepted = []
        for segment in segments:
            log_probability = getattr(segment, "avg_logprob", -1.0)
            # This heuristic is not the same calibration as Vosk word confidence.
            if min_confidence and math.exp(min(0.0, log_probability)) < min_confidence:
                continue
            if getattr(segment, "no_speech_prob", 0.0) > 0.85:
                continue
            accepted.append(segment.text)
        return normalize_text(" ".join(accepted))
