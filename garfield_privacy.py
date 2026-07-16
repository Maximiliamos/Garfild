from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable

SENSITIVE_COMMAND_PATTERNS = (
    re.compile(r"\bнапечатай\s+(?:пароль|код|токен|ключ)\b", re.IGNORECASE),
    re.compile(r"\bвведи\s+(?:пароль|код|токен|ключ)\b", re.IGNORECASE),
    re.compile(r"\b(?:api[-_ ]?key|token|пароль)\b", re.IGNORECASE),
)

BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")

GENERIC_SECRET_PATTERN = re.compile(
    r"(?i)\b("
    r"sk-[A-Za-z0-9_-]{12,}|"
    r"AIza[A-Za-z0-9_-]{20,}|"
    r"xai-[A-Za-z0-9_-]{12,}"
    r")\b"
)


def looks_sensitive(text: str) -> bool:
    return any(pattern.search(text) for pattern in SENSITIVE_COMMAND_PATTERNS)


def redact_sensitive_text(
    text: str,
    known_secrets: Iterable[str] = (),
) -> str:
    result = text

    for secret in known_secrets:
        secret = secret.strip()
        if secret:
            result = result.replace(secret, "[REDACTED]")

    result = BEARER_PATTERN.sub("Bearer [REDACTED]", result)
    result = GENERIC_SECRET_PATTERN.sub("[REDACTED]", result)
    return result


class SecretRedactingFilter(logging.Filter):
    def __init__(self, secret_supplier: Callable[[], Iterable[str]]) -> None:
        super().__init__()
        self.secret_supplier = secret_supplier

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = redact_sensitive_text(
            message,
            self.secret_supplier(),
        )
        record.args = ()
        return True
