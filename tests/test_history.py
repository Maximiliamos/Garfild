from __future__ import annotations

from garfield_best import ConversationHistory


def test_history_keeps_only_configured_number_of_turns() -> None:
    history = ConversationHistory(max_turns=2)

    history.add("первый", "ответ один")
    history.add("второй", "ответ два")
    history.add("третий", "ответ три")

    assert history.turns == [
        ("второй", "ответ два"),
        ("третий", "ответ три"),
    ]


def test_history_converts_turns_to_llm_messages() -> None:
    history = ConversationHistory(max_turns=2)
    history.add("привет", "здравствуйте")

    assert history.as_messages() == [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": "здравствуйте"},
    ]
