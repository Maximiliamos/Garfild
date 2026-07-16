from __future__ import annotations

from garfield_privacy import looks_sensitive, redact_sensitive_text


def test_redacts_known_secret() -> None:
    text = "Ошибка API с ключом secret-value-123"

    assert redact_sensitive_text(text, ["secret-value-123"]) == "Ошибка API с ключом [REDACTED]"


def test_redacts_bearer_token() -> None:
    result = redact_sensitive_text("Authorization: Bearer abcdefghijklmnopqrstuvwxyz")

    assert "abcdefghijklmnopqrstuvwxyz" not in result
    assert result == "Authorization: Bearer [REDACTED]"


def test_redacts_common_provider_secret_formats() -> None:
    result = redact_sensitive_text("OpenAI sk-abcdefghijklmnop and xAI xai-abcdefghijklmnop")

    assert result == "OpenAI [REDACTED] and xAI [REDACTED]"


def test_detects_sensitive_command_text() -> None:
    assert looks_sensitive("напечатай пароль super-secret")
    assert looks_sensitive("Authorization token is missing")
    assert not looks_sensitive("объясни квантовую запутанность")
