from __future__ import annotations

from pathlib import Path

from garfield_actions import ActionDefinition, ActionResult
from garfield_best import AssistantCore, HistoryPolicy
from garfield_intents import RiskLevel

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
    assert assistant.pending_action is None
    assert assistant.history.turns == []


def test_negated_close_window_does_not_execute_desktop_action(monkeypatch, tmp_path: Path) -> None:
    config = FakeConfig(
        skills_path=str(tmp_path / "skills.json"),
        enable_desktop_commands=True,
    )
    assistant = AssistantCore(config)
    called = False

    def close_window() -> str:
        nonlocal called
        called = True
        return "Закрываю окно."

    monkeypatch.setattr(assistant.desktop, "close_window", close_window)

    assistant.handle("не закрывай окно")

    assert called is False


def test_destructive_action_requires_full_confirmation(monkeypatch, tmp_path: Path) -> None:
    config = FakeConfig(
        skills_path=str(tmp_path / "skills.json"),
        enable_desktop_commands=True,
    )
    assistant = AssistantCore(config)
    calls = 0

    def close_window() -> ActionResult:
        nonlocal calls
        calls += 1
        return ActionResult(True, "Закрываю окно.")

    monkeypatch.setitem(
        assistant.actions._actions,
        "window.close",
        ActionDefinition(
            "window.close",
            "Закрытие окна",
            close_window,
            RiskLevel.DESTRUCTIVE,
        ),
    )

    prompt = assistant.handle("закрой окно")
    plain_yes = assistant.handle("да")
    confirmed = assistant.handle("подтверждаю закрытие окна")

    assert prompt is not None and "Подтвердите" in prompt.text
    assert plain_yes is not None and "Для подтверждения" in plain_yes.text
    assert confirmed is not None and confirmed.text == "Закрываю окно."
    assert calls == 1
    assert assistant.pending_action is None


def test_cancellation_clears_pending_action(tmp_path: Path) -> None:
    config = FakeConfig(
        skills_path=str(tmp_path / "skills.json"),
        enable_desktop_commands=True,
    )
    assistant = AssistantCore(config)

    assistant.handle("закрой окно")
    reply = assistant.handle("нет")

    assert reply is not None and reply.text == "Команда отменена."
    assert assistant.pending_action is None


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


def test_sensitive_llm_dialogue_is_redacted_in_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = FakeConfig(skills_path=str(tmp_path / "skills.json"))
    config.openai_api_key_env = "OPENAI_API_KEY"
    monkeypatch.setenv("OPENAI_API_KEY", "known-secret-value")
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
