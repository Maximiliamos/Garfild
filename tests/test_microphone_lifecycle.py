from __future__ import annotations

import threading
from pathlib import Path

import garfield_flagship
from garfield_best import VoiceRecognizer
from garfield_flagship import FlagshipConfig, FlagshipRuntime


class FakeStream:
    def __init__(self) -> None:
        self.aborted = False
        self.closed = False
        self.read_calls = 0

    def abort(self) -> None:
        self.aborted = True

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback

    def read(self, block_size: int):
        self.read_calls += 1
        raise AssertionError(f"unexpected read of {block_size}")


class FakeSoundDevice:
    def __init__(self, stream: FakeStream) -> None:
        self.stream = stream

    def InputStream(self, **kwargs) -> FakeStream:
        del kwargs
        return self.stream


class FakeKaldiRecognizer:
    def __init__(self, model, sample_rate) -> None:
        del model, sample_rate

    def SetWords(self, enabled: bool) -> None:
        del enabled

    def FinalResult(self) -> str:
        return '{"text": ""}'


def bare_recognizer(stream: FakeStream) -> VoiceRecognizer:
    recognizer = VoiceRecognizer.__new__(VoiceRecognizer)
    recognizer.sd = FakeSoundDevice(stream)
    recognizer.KaldiRecognizer = FakeKaldiRecognizer
    recognizer.model = object()
    recognizer.sample_rate = 16_000
    recognizer.device = type("Device", (), {"index": 1})()
    recognizer._lock = threading.RLock()
    recognizer._closed = False
    recognizer._active_stream = None
    return recognizer


def test_voice_recognizer_close_aborts_and_closes_active_stream() -> None:
    stream = FakeStream()
    recognizer = bare_recognizer(stream)
    recognizer._active_stream = stream

    recognizer.close()

    assert recognizer._closed is True
    assert recognizer._active_stream is None
    assert stream.aborted is True
    assert stream.closed is True


def test_voice_recognizer_honours_pre_cancelled_listen() -> None:
    stream = FakeStream()
    recognizer = bare_recognizer(stream)
    cancel_event = threading.Event()
    cancel_event.set()

    assert recognizer.listen(5, cancel_event=cancel_event) == ""
    assert stream.read_calls == 0


class RuntimeRecognizer:
    def __init__(self, result: str = "") -> None:
        self.result = result
        self.closed = False
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancel_event: threading.Event | None = None

    def listen(self, timeout_sec: int, **kwargs) -> str:
        del timeout_sec
        self.cancel_event = kwargs.get("cancel_event")
        self.started.set()
        self.release.wait(timeout=2)
        return self.result

    def close(self) -> None:
        self.closed = True
        self.release.set()


def make_runtime(tmp_path: Path) -> FlagshipRuntime:
    return FlagshipRuntime(
        FlagshipConfig(
            use_llm=False,
            input_mode="voice",
            vosk_model_path=str(tmp_path / "vosk"),
            skills_path=str(tmp_path / "skills.json"),
        )
    )


def test_generation_guard_drops_result_from_old_voice_worker(
    tmp_path: Path,
) -> None:
    runtime = make_runtime(tmp_path)
    recognizer = RuntimeRecognizer("stale command")
    runtime.voice_recognizer = recognizer  # type: ignore[assignment]
    runtime.listening_enabled = True
    submitted: list[str] = []
    runtime.submit_text = lambda text, source="manual": submitted.append(text) or True  # type: ignore[method-assign]

    worker = threading.Thread(target=runtime._voice_worker_loop)
    worker.start()
    assert recognizer.started.wait(timeout=1)
    runtime.voice_generation += 1
    recognizer.release.set()
    worker.join(timeout=2)

    assert submitted == []
    assert not worker.is_alive()
    assert recognizer.cancel_event is runtime.voice_cancel_event


def test_apply_audio_settings_closes_old_recognizer_and_increments_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = make_runtime(tmp_path)
    old = RuntimeRecognizer()
    new = RuntimeRecognizer()
    runtime.voice_recognizer = old  # type: ignore[assignment]
    monkeypatch.setattr(
        garfield_flagship.core,
        "VoiceRecognizer",
        lambda *args, **kwargs: new,
    )
    monkeypatch.setattr(
        garfield_flagship.core,
        "describe_audio_device",
        lambda kind, index: f"{kind}:{index}",
    )

    summary = runtime.apply_audio_settings(3, 4)

    assert old.closed is True
    assert runtime.voice_recognizer is new
    assert runtime.voice_generation == 1
    assert runtime.config.input_device_index == 3
    assert runtime.config.output_device_index == 4
    assert summary == "Микрофон: input:3. Вывод: output:4."
