from __future__ import annotations

import queue
import threading
from pathlib import Path

from garfield_flagship import (
    FlagshipConfig,
    FlagshipRuntime,
    RuntimeEvent,
    TTSQueue,
)


def make_runtime(tmp_path: Path, **overrides) -> FlagshipRuntime:
    return FlagshipRuntime(
        FlagshipConfig(
            use_llm=False,
            skills_path=str(tmp_path / "skills.json"),
            **overrides,
        )
    )


def test_runtime_queues_and_session_buffer_are_bounded(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path, persist_session_history=True)

    assert runtime.events.maxsize == 256
    assert runtime.command_queue.maxsize == 64
    assert runtime.session_lines.maxlen == 2_000

    for index in range(2_005):
        runtime.emit("status", f"line {index}")

    assert len(runtime.session_lines) == 2_000
    assert "line 5" in runtime.session_lines[0]


def test_submit_text_rejects_empty_long_and_full_queue(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)

    assert runtime.submit_text("   ") is False
    assert runtime.submit_text("x" * 8_001) is False
    for index in range(64):
        assert runtime.submit_text(f"command {index}") is True

    assert runtime.submit_text("one too many") is False
    messages = [event.text for event in runtime.drain_events()]
    assert any("слишком длинная" in message for message in messages)
    assert any("Очередь команд заполнена" in message for message in messages)


def test_full_event_queue_drops_status_but_keeps_assistant_event(
    tmp_path: Path,
) -> None:
    runtime = make_runtime(tmp_path)
    for index in range(256):
        runtime._put_event(RuntimeEvent("status", str(index), 0.0))

    runtime._put_event(RuntimeEvent("status", "dropped", 0.0))
    assert runtime.events.qsize() == 256
    assert all(event.text != "dropped" for event in list(runtime.events.queue))

    runtime._put_event(RuntimeEvent("assistant", "important", 0.0))
    assert runtime.events.qsize() == 256
    assert any(event.text == "important" for event in list(runtime.events.queue))


def test_command_worker_consumes_sentinel_once(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    worker = threading.Thread(target=runtime._command_worker_loop)
    worker.start()

    runtime.command_queue.put_nowait(None)
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert runtime.command_queue.unfinished_tasks == 0


def test_runtime_stop_is_idempotent_and_joins_command_worker(
    tmp_path: Path,
) -> None:
    runtime = make_runtime(tmp_path)
    runtime.command_worker.start()

    runtime.stop()
    runtime.stop()

    assert runtime.stop_event.is_set()
    assert not runtime.command_worker.is_alive()


def test_tts_queue_is_bounded_without_blocking() -> None:
    tts = TTSQueue("Garfield", enabled=True)

    for index in range(40):
        tts.speak(f"message {index}")

    assert tts.queue.maxsize == 32
    assert tts.queue.qsize() == 32

    while True:
        try:
            tts.queue.get_nowait()
            tts.queue.task_done()
        except queue.Empty:
            break
