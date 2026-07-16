from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

MAX_LLM_RESPONSE_BYTES = 2_000_000


@dataclass(frozen=True)
class CacheEntry:
    answer: str
    created_at: float


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str
    cached: bool = False


class LLMError(RuntimeError):
    pass


class LLMNetworkError(LLMError):
    pass


class LLMAuthenticationError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMResponseFormatError(LLMError):
    pass


class LLMEmptyResponseError(LLMResponseFormatError):
    pass


class LLMResponseTooLargeError(LLMResponseFormatError):
    pass


def build_answer_cache_key(
    *,
    provider: str,
    model: str,
    system_prompt: str,
    history: list[dict[str, str]],
    user_text: str,
) -> str:
    payload = {
        "provider": provider,
        "model": model,
        "system_prompt": system_prompt,
        "history": history,
        "user_text": user_text,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def is_cache_entry_valid(entry: CacheEntry, ttl_sec: int) -> bool:
    return time.monotonic() - entry.created_at <= ttl_sec


def require_non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise LLMResponseFormatError(f"Поле {field_name} должно быть строкой.")
    value = value.strip()
    if not value:
        raise LLMEmptyResponseError(f"Поле {field_name} является пустым.")
    return value


def validate_response_size(
    response: Any,
    max_bytes: int = MAX_LLM_RESPONSE_BYTES,
) -> None:
    content_length = response.headers.get("Content-Length", "").strip()
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise LLMResponseFormatError("Некорректный Content-Length в ответе LLM.") from error
        if declared_size > max_bytes:
            raise LLMResponseTooLargeError("Ответ LLM превышает допустимый размер.")

    if len(response.content) > max_bytes:
        raise LLMResponseTooLargeError("Ответ LLM превышает допустимый размер.")


def raise_for_llm_status(response: Any) -> None:
    if response.status_code in {401, 403}:
        raise LLMAuthenticationError("LLM отклонила учётные данные.")
    if response.status_code == 429:
        raise LLMRateLimitError("Превышен лимит запросов к LLM.")
    response.raise_for_status()
