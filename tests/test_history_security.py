from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from garfield_dashboard.services import DashboardPaths, RuntimeAdapter
from garfield_flagship import FlagshipConfig, FlagshipRuntime
from garfield_privacy import SecretRedactingFilter


class InMemorySecretStore:
    def __init__(self, **values: str) -> None:
        self.values = values

    def get(self, provider: str) -> str:
        return self.values.get(provider, "")

    def set(self, provider: str, value: str) -> None:
        self.values[provider] = value

    def delete(self, provider: str) -> None:
        self.values.pop(provider, None)

    def is_configured(self, provider: str) -> bool:
        return bool(self.get(provider))


def test_emit_does_not_persist_by_default(tmp_path: Path) -> None:
    runtime = FlagshipRuntime(
        FlagshipConfig(
            use_llm=False,
            skills_path=str(tmp_path / "skills.json"),
        )
    )

    runtime.emit("user", "ordinary message")

    assert not runtime.session_lines
    event = runtime.drain_events()[0]
    assert event.text == "ordinary message"
    assert event.persist is True


def test_sensitive_emit_uses_placeholder_for_persistent_history(
    tmp_path: Path,
) -> None:
    runtime = FlagshipRuntime(
        FlagshipConfig(
            use_llm=False,
            persist_session_history=True,
            skills_path=str(tmp_path / "skills.json"),
        )
    )

    runtime.emit(
        "user",
        "[gui] Команда локального ввода текста",
        sensitive=True,
    )

    assert len(runtime.session_lines) == 1
    assert "Чувствительные данные скрыты" in runtime.session_lines[0]
    assert runtime.drain_events()[0].sensitive is True


def test_sensitive_text_command_never_enters_event_or_session(
    tmp_path: Path,
) -> None:
    runtime = FlagshipRuntime(
        FlagshipConfig(
            use_llm=False,
            persist_session_history=True,
            skills_path=str(tmp_path / "skills.json"),
        )
    )
    runtime.assistant.handle = lambda _text: None  # type: ignore[method-assign]

    runtime._process_command("напечатай пароль super-secret", "gui")

    events = runtime.drain_events()
    assert all("super-secret" not in event.text for event in events)
    assert all("super-secret" not in line for line in runtime.session_lines)
    assert events[0].sensitive is True


def test_secret_redacting_filter_rewrites_formatted_log_message() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request failed for token %s",
        args=("known-secret",),
        exc_info=None,
    )
    filter_ = SecretRedactingFilter(lambda: ["known-secret"])

    assert filter_.filter(record) is True
    assert record.getMessage() == "request failed for token [REDACTED]"


@dataclass
class _Assistant:
    llm_client: object | None = None


@dataclass
class _Runtime:
    config: FlagshipConfig
    assistant: _Assistant


def _adapter(tmp_path: Path, store: InMemorySecretStore) -> RuntimeAdapter:
    runtime = _Runtime(FlagshipConfig(use_llm=False), _Assistant())
    return RuntimeAdapter(
        runtime,
        save_config=lambda _config: None,
        paths=DashboardPaths(
            base_dir=tmp_path,
            config_path=tmp_path / "config.json",
            log_path=tmp_path / "app.log",
            session_log_path=tmp_path / "garfield_session_history.txt",
        ),
        secret_store=store,  # type: ignore[arg-type]
    )


def test_export_redacts_secrets_and_skips_non_persistent_events(
    tmp_path: Path,
) -> None:
    adapter = _adapter(
        tmp_path,
        InMemorySecretStore(openai="known-secret"),
    )

    txt_path, json_path = adapter.export_history(
        [
            {
                "role": "user",
                "text": "token known-secret",
                "timestamp": "2026-01-01 00:00:00",
                "sensitive": False,
                "persist": True,
            },
            {
                "role": "status",
                "text": "temporary detail",
                "timestamp": "2026-01-01 00:00:01",
                "sensitive": False,
                "persist": False,
            },
        ]
    )

    assert "known-secret" not in txt_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload[0]["text"] == "token [REDACTED]"
    assert len(payload) == 1


def test_delete_saved_history_removes_all_three_files(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, InMemorySecretStore())
    paths = [
        adapter.paths.session_log_path,
        tmp_path / "garfield_session_history_export.txt",
        tmp_path / "garfield_session_history_export.json",
    ]
    for path in paths:
        path.write_text("history", encoding="utf-8")

    deleted = adapter.delete_saved_history()

    assert set(deleted) == set(paths)
    assert all(not path.exists() for path in paths)
