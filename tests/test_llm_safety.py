from __future__ import annotations

import time
from pathlib import Path

import pytest

from garfield_best import AssistantCore, LLMClient
from garfield_llm import (
    CacheEntry,
    LLMAuthenticationError,
    LLMEmptyResponseError,
    LLMRateLimitError,
    LLMResponseTooLargeError,
    build_answer_cache_key,
    is_cache_entry_valid,
    raise_for_llm_status,
    require_non_empty_string,
    validate_response_size,
)

from .conftest import FakeConfig, FakeLLM


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: object | None = None,
        content: bytes = b"{}",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self) -> object:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    def post(self, *args, **kwargs) -> FakeResponse:
        del args, kwargs
        return self.response


class FakeSecretStore:
    def get(self, provider: str) -> str:
        del provider
        return "test-secret"


def test_cache_key_changes_with_provider_model_prompt_and_history() -> None:
    base = {
        "provider": "openai",
        "model": "gpt",
        "system_prompt": "system",
        "history": [{"role": "user", "content": "before"}],
        "user_text": "question",
    }
    key = build_answer_cache_key(**base)

    for field, value in [
        ("provider", "groq"),
        ("model", "other"),
        ("system_prompt", "changed"),
        ("history", []),
        ("user_text", "other question"),
    ]:
        changed = dict(base)
        changed[field] = value
        assert build_answer_cache_key(**changed) != key


def test_cache_entry_ttl() -> None:
    fresh = CacheEntry("answer", time.monotonic())
    expired = CacheEntry("answer", time.monotonic() - 20)

    assert is_cache_entry_valid(fresh, 10) is True
    assert is_cache_entry_valid(expired, 10) is False


def test_require_non_empty_string_rejects_wrong_or_empty_values() -> None:
    with pytest.raises(Exception, match="должно быть строкой"):
        require_non_empty_string(42, "text")
    with pytest.raises(LLMEmptyResponseError, match="пустым"):
        require_non_empty_string("  ", "text")


def test_response_size_checks_header_and_actual_content() -> None:
    with pytest.raises(LLMResponseTooLargeError):
        validate_response_size(FakeResponse(headers={"Content-Length": "2000001"}))
    with pytest.raises(LLMResponseTooLargeError):
        validate_response_size(FakeResponse(content=b"x" * 21), max_bytes=20)


def test_http_status_keeps_auth_and_rate_limit_distinct() -> None:
    with pytest.raises(LLMAuthenticationError):
        raise_for_llm_status(FakeResponse(status_code=401))
    with pytest.raises(LLMRateLimitError):
        raise_for_llm_status(FakeResponse(status_code=429))


def test_openai_compatible_client_returns_unified_result() -> None:
    client = LLMClient(
        "openai",
        "https://example.invalid/v1/chat/completions",
        "test-model",
        "OPENAI_API_KEY",
        secret_store=FakeSecretStore(),  # type: ignore[arg-type]
    )
    client.session = FakeSession(
        FakeResponse(
            payload={"choices": [{"message": {"content": "  valid answer  "}}]},
            content=b'{"choices":[]}',
        )
    )

    result = client.ask(
        "question",
        "Garfield",
        _EmptyHistory(),
    )

    assert result.text == "valid answer"
    assert result.provider == "openai"
    assert result.model == "test-model"
    assert result.cached is False


class _EmptyHistory:
    def as_messages(self) -> list[dict[str, str]]:
        return []


def test_assistant_cache_uses_context_and_skips_sensitive_queries(
    tmp_path: Path,
) -> None:
    config = FakeConfig(skills_path=str(tmp_path / "skills.json"))
    assistant = AssistantCore(config)
    client = FakeLLM("answer")
    assistant.llm_client = client

    assert assistant._ask_llm_or_fallback("ordinary question") == "answer"
    assert assistant._ask_llm_or_fallback("ordinary question") == "answer"
    assert len(client.calls) == 1

    assistant.history.add("before", "context")
    assert assistant._ask_llm_or_fallback("ordinary question") == "answer"
    assert len(client.calls) == 2

    assert assistant._ask_llm_or_fallback("token sk-abcdefghijklmnop") == "answer"
    assert assistant._ask_llm_or_fallback("token sk-abcdefghijklmnop") == "answer"
    assert len(client.calls) == 4


def test_fallback_answers_are_not_cached(tmp_path: Path) -> None:
    config = FakeConfig(skills_path=str(tmp_path / "skills.json"))
    assistant = AssistantCore(config)
    assistant.llm_client = None

    first = assistant._ask_llm_or_fallback("unknown question")
    second = assistant._ask_llm_or_fallback("unknown question")

    assert first == second
    assert assistant.answer_cache == {}
