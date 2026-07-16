from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from garfield_dashboard.services import DashboardPaths, RuntimeAdapter
from garfield_flagship import FlagshipConfig, save_config
from garfield_secrets import (
    SecretMigrationError,
    SecretStore,
    migrate_plaintext_secrets,
)


class InMemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []

    def get(self, provider: str) -> str:
        return self.values.get(provider, "")

    def set(self, provider: str, value: str) -> None:
        value = value.strip()
        if not value:
            raise ValueError("empty")
        self.values[provider] = value

    def delete(self, provider: str) -> None:
        self.deleted.append(provider)
        self.values.pop(provider, None)

    def is_configured(self, provider: str) -> bool:
        return bool(self.get(provider))


class FailingSecretStore(InMemorySecretStore):
    def set(self, provider: str, value: str) -> None:
        raise RuntimeError("backend unavailable")


def test_legacy_key_is_migrated_and_removed_from_json(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "assistant_name": "Test",
                "openai_api_key": "legacy-secret",
            }
        ),
        encoding="utf-8",
    )
    store = InMemorySecretStore()

    config = FlagshipConfig.load(path, secret_store=store)

    assert config.assistant_name == "Test"
    assert store.get("openai") == "legacy-secret"
    assert "openai_api_key" not in json.loads(path.read_text(encoding="utf-8"))
    assert not hasattr(config, "openai_api_key")


def test_failed_migration_keeps_plaintext_source_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    original = '{"openai_api_key": "legacy-secret"}'
    path.write_text(original, encoding="utf-8")

    with pytest.raises(SecretMigrationError):
        FlagshipConfig.load(path, secret_store=FailingSecretStore())

    assert path.read_text(encoding="utf-8") == original


def test_migration_removes_fields_only_after_all_writes_succeed() -> None:
    raw = {
        "openai_api_key": "first",
        "groq_api_key": "second",
    }

    with pytest.raises(SecretMigrationError):
        migrate_plaintext_secrets(raw, FailingSecretStore())

    assert raw == {
        "openai_api_key": "first",
        "groq_api_key": "second",
    }


def test_empty_legacy_secret_field_is_removed_without_keyring_write() -> None:
    raw = {"xai_api_key": "", "assistant_name": "Test"}
    store = InMemorySecretStore()

    assert migrate_plaintext_secrets(raw, store) is True

    assert raw == {"assistant_name": "Test"}
    assert store.values == {}


def test_environment_has_priority_over_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = InMemorySecretStore()
    backend.set("openai", "stored-secret")
    store = SecretStore()
    store._backend = lambda: _KeyringAdapter(backend)  # type: ignore[method-assign]
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")

    assert store.get("openai") == "environment-secret"


class _KeyringAdapter:
    def __init__(self, backend: InMemorySecretStore) -> None:
        self.backend = backend

    def get_password(self, service: str, provider: str) -> str:
        del service
        return self.backend.get(provider)


@dataclass
class _Assistant:
    llm_client: object | None = None


@dataclass
class _Runtime:
    config: FlagshipConfig
    assistant: _Assistant


def _adapter(tmp_path: Path, store: InMemorySecretStore) -> RuntimeAdapter:
    config = FlagshipConfig(use_llm=False)
    runtime = _Runtime(config=config, assistant=_Assistant())
    return RuntimeAdapter(
        runtime,
        save_config=lambda value: save_config(value, tmp_path / "config.json"),
        paths=DashboardPaths(
            base_dir=tmp_path,
            config_path=tmp_path / "config.json",
            log_path=tmp_path / "app.log",
            session_log_path=tmp_path / "history.txt",
        ),
        secret_store=store,  # type: ignore[arg-type]
    )


def test_empty_new_value_does_not_delete_existing_secret(tmp_path: Path) -> None:
    store = InMemorySecretStore()
    store.set("openai", "existing")
    adapter = _adapter(tmp_path, store)

    with pytest.raises(ValueError):
        adapter.save_secret("openai", "")

    assert store.get("openai") == "existing"
    assert store.deleted == []


def test_secret_deletion_requires_dedicated_operation(tmp_path: Path) -> None:
    store = InMemorySecretStore()
    store.set("openai", "existing")
    adapter = _adapter(tmp_path, store)

    adapter.delete_secret("openai")

    assert store.get("openai") == ""
    assert store.deleted == ["openai"]
