from __future__ import annotations

from pathlib import Path

from garfield_best import AssistantCore

from .conftest import FakeConfig


def test_help_command_is_handled_locally(tmp_path: Path) -> None:
    assistant = AssistantCore(FakeConfig(skills_path=str(tmp_path / "skills.json")))

    reply = assistant.handle("помощь")

    assert reply is not None
    assert reply.text
    assert assistant.llm_client is None


def test_power_command_stays_disabled_by_default(tmp_path: Path) -> None:
    assistant = AssistantCore(FakeConfig(skills_path=str(tmp_path / "skills.json")))

    reply = assistant.handle("выключи компьютер")

    assert reply is not None
    assert assistant.pending_power_action is None
