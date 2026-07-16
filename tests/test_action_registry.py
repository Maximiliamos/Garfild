from __future__ import annotations

import pytest

from garfield_actions import ActionDefinition, ActionRegistry, ActionResult
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
