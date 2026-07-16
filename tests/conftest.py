from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from garfield_llm import LLMResult


@dataclass
class FakeConfig:
    assistant_name: str = "Гарфилд"
    remember_turns: int = 6
    max_cached_answers: int = 20
    answer_cache_ttl_sec: int = 900
    allow_power_commands: bool = False
    enable_desktop_commands: bool = False
    require_name_prefix: bool = False
    command_confirmation_timeout_sec: int = 20
    confirm_phrases: list[str] = field(default_factory=lambda: ["да", "подтверждаю"])
    cancel_phrases: list[str] = field(default_factory=lambda: ["нет", "отмена", "не надо"])
    skills_path: str = ""
    use_llm: bool = False


class FakeLLM:
    def __init__(self, answer: str = "Тестовый ответ") -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []
        self.provider = "fake"
        self.model = "fake-model"

    def is_available(self) -> bool:
        return True

    def system_prompt(self, assistant_name: str) -> str:
        return f"System for {assistant_name}"

    def ask(self, text: str, assistant_name: str, history: Any) -> LLMResult:
        self.calls.append(
            {
                "text": text,
                "assistant_name": assistant_name,
                "history": history.as_messages(),
            }
        )
        return LLMResult(
            text=self.answer,
            provider=self.provider,
            model=self.model,
        )


class FakeTTS:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.enabled = True

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def speak(self, text: str) -> None:
        self.messages.append(text)

    def interrupt(self) -> None:
        pass

    def is_busy(self) -> bool:
        return False


@pytest.fixture
def fake_config(tmp_path: Path) -> FakeConfig:
    return FakeConfig(skills_path=str(tmp_path / "skills.json"))
