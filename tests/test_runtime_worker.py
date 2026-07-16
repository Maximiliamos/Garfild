from __future__ import annotations

from pathlib import Path

from garfield_best import AssistantReply
from garfield_flagship import FlagshipConfig, FlagshipRuntime

from .conftest import FakeTTS


def test_worker_processes_command_without_audio_or_windows_actions(tmp_path: Path) -> None:
    config = FlagshipConfig(
        input_mode="keyboard",
        auto_listen=False,
        tts_enabled=False,
        use_llm=False,
        enable_desktop_commands=False,
        allow_power_commands=False,
        skills_path=str(tmp_path / "skills.json"),
    )
    runtime = FlagshipRuntime(config)
    runtime.tts = FakeTTS()

    runtime.command_worker.start()
    try:
        runtime.submit_text("привет")
        runtime.command_queue.join()

        events = runtime.drain_events()
        assert any(event.kind == "user" for event in events)
        assert any(event.kind == "assistant" and event.text for event in events)
        assert runtime.command_worker.is_alive()
    finally:
        runtime.stop_event.set()
        runtime.command_worker.join(timeout=2)


def test_worker_survives_assistant_exception(monkeypatch, tmp_path: Path) -> None:
    config = FlagshipConfig(
        input_mode="keyboard",
        auto_listen=False,
        tts_enabled=False,
        use_llm=False,
        enable_desktop_commands=False,
        allow_power_commands=False,
        skills_path=str(tmp_path / "skills.json"),
    )
    runtime = FlagshipRuntime(config)
    runtime.tts = FakeTTS()
    calls = 0

    def handle(text: str) -> AssistantReply:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("broken response")
        return AssistantReply("Вторая команда выполнена")

    monkeypatch.setattr(runtime.assistant, "handle", handle)

    runtime.command_worker.start()
    try:
        runtime.submit_text("первая")
        runtime.submit_text("вторая")
        runtime.command_queue.join()

        events = runtime.drain_events()
        assert any("Код ошибки" in event.text for event in events)
        assert any("Вторая команда выполнена" in event.text for event in events)
        assert runtime.command_worker.is_alive()
        assert runtime.command_worker_last_error is not None
        assert runtime.command_worker_last_activity > 0
    finally:
        runtime.stop_event.set()
        runtime.command_worker.join(timeout=2)
