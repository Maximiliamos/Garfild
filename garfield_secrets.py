from __future__ import annotations

import os
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

SERVICE_NAME = "GarfildAssistant"
PROVIDERS = ("nvidia", "openai", "gemini", "groq", "xai")


class SecretStoreUnavailable(RuntimeError):
    pass


class SecretMigrationError(RuntimeError):
    pass


@dataclass
class SecretStore:
    service_name: str = SERVICE_NAME

    def _backend(self) -> Any:
        try:
            import keyring
        except ImportError as error:
            raise SecretStoreUnavailable("Пакет keyring не установлен.") from error
        return keyring

    def get(self, provider: str) -> str:
        env_name = f"{provider.upper()}_API_KEY"
        env_value = os.getenv(env_name, "").strip()
        if env_value:
            return env_value

        keyring = self._backend()
        return (keyring.get_password(self.service_name, provider) or "").strip()

    def set(self, provider: str, value: str) -> None:
        value = value.strip()
        if not value:
            raise ValueError("Нельзя сохранить пустой API-ключ.")
        self._backend().set_password(self.service_name, provider, value)

    def delete(self, provider: str) -> None:
        keyring = self._backend()
        with suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(self.service_name, provider)

    def is_configured(self, provider: str) -> bool:
        return bool(self.get(provider))


def migrate_plaintext_secrets(
    raw_data: dict[str, Any],
    secret_store: SecretStore,
) -> bool:
    pending: list[tuple[str, str, str]] = []
    legacy_fields: list[str] = []
    for provider in PROVIDERS:
        field_name = f"{provider}_api_key"
        if field_name in raw_data:
            legacy_fields.append(field_name)
        secret = str(raw_data.get(field_name, "")).strip()
        if secret:
            pending.append((provider, field_name, secret))

    if not legacy_fields:
        return False

    if pending:
        try:
            for provider, _, secret in pending:
                secret_store.set(provider, secret)
        except Exception as error:
            raise SecretMigrationError(
                "Не удалось перенести API-ключи в безопасное хранилище; исходный файл конфигурации не изменён."
            ) from error

    for field_name in legacy_fields:
        raw_data.pop(field_name, None)
    return True
