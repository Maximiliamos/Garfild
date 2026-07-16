from __future__ import annotations

import pytest

from garfield_actions import (
    ActionContext,
    ActionDefinition,
    ActionRegistry,
    ActionResult,
    create_default_registry,
)
from garfield_intents import RiskLevel


def test_registry_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="Неизвестное действие"):
        ActionRegistry().execute("unknown.action", {})


def test_registry_rejects_unknown_arguments() -> None:
    registry = ActionRegistry()
    registry.register(
        ActionDefinition(
            action_id="assistant.say",
            display_name="Ответ",
            handler=lambda **arguments: ActionResult(True, str(arguments["text"])),
            risk=RiskLevel.SAFE,
            allowed_arguments=frozenset({"text"}),
        )
    )

    with pytest.raises(ValueError, match="Недопустимые аргументы"):
        registry.execute(
            "assistant.say",
            {"text": "ok", "command": "shutdown"},
        )


def test_user_arguments_cannot_change_action_id() -> None:
    registry = ActionRegistry()
    registry.register(
        ActionDefinition(
            action_id="assistant.say",
            display_name="Ответ",
            handler=lambda **arguments: ActionResult(True, str(arguments["text"])),
            risk=RiskLevel.SAFE,
            allowed_arguments=frozenset({"text"}),
        )
    )

    with pytest.raises(ValueError):
        registry.execute(
            "assistant.say",
            {"text": "hello", "action_id": "system.shutdown"},
        )


def test_text_actions_have_distinct_risk_levels() -> None:
    registry = create_default_registry(
        ActionContext(platform_name="Windows", desktop_enabled=True, power_enabled=False)
    )

    expected = {
        "text.copy": RiskLevel.VISIBLE,
        "text.select_all": RiskLevel.VISIBLE,
        "text.paste": RiskLevel.SENSITIVE,
        "text.cut": RiskLevel.DESTRUCTIVE,
        "text.delete_last_word": RiskLevel.DESTRUCTIVE,
        "text.delete_all": RiskLevel.DESTRUCTIVE,
        "message.send": RiskLevel.DESTRUCTIVE,
        "text.undo": RiskLevel.VISIBLE,
        "text.save_as": RiskLevel.VISIBLE,
    }

    assert {action_id: registry.get(action_id).risk for action_id in expected} == expected
    with pytest.raises(ValueError):
        registry.get("text.shortcut")
