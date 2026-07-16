from __future__ import annotations

from pathlib import Path

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
