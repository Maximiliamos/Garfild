"""Voice output worker extracted from the legacy flagship entrypoint."""
from __future__ import annotations

import logging
import queue
import threading

import garfield_best as core


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
        self.queue: queue.Queue[str | None] = queue.Queue()
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
        self.queue.put(None)
        self.worker.join(timeout=5)

    def speak(self, text: str) -> None:
        if self.enabled and text.strip():
            self.queue.put(text)

    def interrupt(self) -> None:
        self.speaker.interrupt()
        while True:
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                self.queue.task_done()

    def set_output_device(self, output_device_index: int | None) -> None:
        self.speaker.set_output_device(output_device_index)

    def set_voice(self, tts_voice: str) -> None:
        self.speaker.set_voice(tts_voice)

    def is_busy(self) -> bool:
        return self.busy_event.is_set() or not self.queue.empty()

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            item = self.queue.get()
            if item is None:
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


