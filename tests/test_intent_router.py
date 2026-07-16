from __future__ import annotations

import pytest

from garfield_intents import IntentRouter, RiskLevel, normalize_command_text


@pytest.mark.parametrize(
    "text",
    [
        "не закрывай окно",
        "не надо закрывать окно",
        "расскажи, как закрыть окно",
        "что произойдёт, если закрыть окно",
    ],
)
def test_close_window_is_not_triggered_by_negated_or_descriptive_text(
    text: str,
) -> None:
    assert IntentRouter().route(text) is None


def test_explicit_close_window_command() -> None:
    intent = IntentRouter().route("закрой окно")

    assert intent is not None
    assert intent.intent_id == "window.close"
    assert intent.risk is RiskLevel.DESTRUCTIVE


def test_text_intent_extracts_argument() -> None:
    intent = IntentRouter().route("Напечатай: Секретный текст!")

    assert intent is not None
    assert intent.intent_id == "text.type"
    assert intent.arguments == {"text": "секретный текст"}


def test_normalization_handles_yo_punctuation_and_spaces() -> None:
    assert normalize_command_text("  Ёлка,   тест! ") == "елка тест"
