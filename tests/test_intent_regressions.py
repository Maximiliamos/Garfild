from __future__ import annotations

from pathlib import Path

from garfield_best import AssistantCore, HistoryPolicy

from .conftest import FakeConfig, FakeLLM


def test_help_command_is_handled_locally(tmp_path: Path) -> None:
    assistant = AssistantCore(FakeConfig(skills_path=str(tmp_path / "skills.json")))

    reply = assistant.handle("помощь")

    assert reply is not None
    assert reply.text
    assert assistant.llm_client is None
    assert reply.history_policy is HistoryPolicy.EXCLUDE
    assert assistant.history.turns == []


def test_power_command_stays_disabled_by_default(tmp_path: Path) -> None:
    assistant = AssistantCore(FakeConfig(skills_path=str(tmp_path / "skills.json")))

    reply = assistant.handle("выключи компьютер")

    assert reply is not None
    assert assistant.pending_power_action is None
    assert assistant.history.turns == []


def test_local_command_is_not_added_to_llm_history(tmp_path: Path) -> None:
    assistant = AssistantCore(FakeConfig(skills_path=str(tmp_path / "skills.json")))

    reply = assistant.handle("напечатай пароль super-secret")

    assert reply is not None
    assert reply.history_policy is HistoryPolicy.EXCLUDE
    assert assistant.history.turns == []


def test_llm_dialogue_is_added_to_history(tmp_path: Path) -> None:
    assistant = AssistantCore(FakeConfig(skills_path=str(tmp_path / "skills.json")))
    fake_llm = FakeLLM("Краткое объяснение")
    assistant.llm_client = fake_llm

    reply = assistant.handle("объясни квантовую запутанность")

    assert reply is not None
    assert reply.history_policy is HistoryPolicy.INCLUDE
    assert assistant.history.turns == [
        ("объясни квантовую запутанность", "Краткое объяснение"),
    ]
    assert fake_llm.calls[0]["history"] == []


def test_sensitive_llm_dialogue_is_redacted_in_history(tmp_path: Path) -> None:
    config = FakeConfig(skills_path=str(tmp_path / "skills.json"))
    config.openai_api_key = "known-secret-value"
    assistant = AssistantCore(config)
    assistant.llm_client = FakeLLM("Ключ known-secret-value или xai-abcdefghijklmnop использовать нельзя")

    reply = assistant.handle("Почему token known-secret-value и xai-abcdefghijklmnop не работает?")

    assert reply is not None
    assert reply.sensitive is True
    assert reply.history_policy is HistoryPolicy.INCLUDE_REDACTED
    assert assistant.history.turns == [
        (
            "почему token [REDACTED] и [REDACTED] не работает?",
            "Ключ [REDACTED] или [REDACTED] использовать нельзя",
        ),
    ]
