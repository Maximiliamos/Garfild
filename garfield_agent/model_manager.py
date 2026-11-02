"""Explicitly approved downloads of known Ollama models, with no shell use."""
from __future__ import annotations

import shutil
import subprocess
import time


class ModelManager:
    ALLOWED = frozenset({
        "qwen2.5:3b", "qwen2.5:7b", "llava:7b", "gemma3:4b",
        "llama3.2:3b", "qwen3:4b",
    })

    def __init__(self):
        self.pending: str | None = None
        self.created_at = 0.0

    def prepare(self, model: str) -> str:
        if model not in self.ALLOWED:
            raise ValueError("Эта модель отсутствует в списке разрешённых: " + ", ".join(sorted(self.ALLOWED)))
        self.pending = model
        self.created_at = time.monotonic()
        return (
            f"Будет загружена модель {model}. Размер может составлять несколько ГБ. "
            "Это скачивание из реестра Ollama. Для запуска в течение 5 минут "
            "введите «подтверди загрузку модели»."
        )

    def confirm(self) -> str:
        model = self.pending
        self.pending = None
        if not model or time.monotonic() - self.created_at > 300:
            return "Загрузка не подтверждена или срок подтверждения истёк"
        executable = shutil.which("ollama")
        if not executable:
            raise RuntimeError("Установите Ollama отдельно: https://ollama.com/download")
        result = subprocess.run(
            [executable, "pull", model], shell=False, capture_output=True,
            text=True, timeout=1200, check=True,
        )
        return f"Модель {model} загружена. " + result.stdout[-500:]

    def cancel(self):
        self.pending = None
        return "Загрузка модели отменена."
