from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from garfield_actions import desktop, system
from garfield_actions.models import ActionContext


def context(
    *,
    desktop_enabled: bool = True,
    power_enabled: bool = True,
    metadata: dict[str, object] | None = None,
    platform_name: str = "Windows",
) -> ActionContext:
    return ActionContext(
        platform_name=platform_name,
        desktop_enabled=desktop_enabled,
        power_enabled=power_enabled,
        metadata=metadata or {},
    )


def test_open_application_uses_fixed_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(
        desktop.subprocess,
        "Popen",
        lambda command, shell: calls.append((command, shell)),
    )

    assert not desktop.open_application(context(desktop_enabled=False), app_id="calculator").success
    assert not desktop.open_application(context(), app_id="cmd").success
    assert desktop.open_application(context(), app_id="calculator").success
    assert calls == [(["calc.exe"], False)]


def test_window_and_text_automation_are_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    class Automation:
        def __init__(self) -> None:
            self.hotkeys: list[tuple[str, ...]] = []

        def hotkey(self, *keys: str) -> None:
            self.hotkeys.append(keys)

    automation = Automation()
    clipboard: list[str] = []
    monkeypatch.setattr(desktop, "_pyautogui", lambda: automation)

    assert desktop.close_window(context(platform_name="Darwin")).success
    assert not desktop.type_text(context(), text="").success
    assert not desktop.type_text(context(), text="hello").success
    assert desktop.type_text(
        context(metadata={"clipboard_writer": clipboard.append}),
        text="hello",
    ).success
    assert automation.hotkeys == [("command", "q"), ("ctrl", "v")]
    assert clipboard == ["hello"]


def test_web_actions_only_open_constructed_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(desktop.webbrowser, "open", opened.append)

    assert desktop.search_web(context(), query="safe query").success
    assert desktop.open_web(context(), url="https://example.test").success
    assert opened == [
        "https://www.google.com/search?q=safe+query",
        "https://example.test",
    ]


def test_project_file_must_stay_inside_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    opened: list[str] = []
    target = tmp_path / "notes.txt"
    target.write_text("ok", encoding="utf-8")
    monkeypatch.setattr(os, "startfile", opened.append)

    assert not desktop.open_project_file(context(), path="notes.txt").success
    project_context = context(metadata={"project_root": tmp_path})
    assert not desktop.open_project_file(project_context, path="../outside.txt").success
    assert not desktop.open_project_file(project_context, path="missing.txt").success
    assert desktop.open_project_file(project_context, path="notes.txt").success
    assert opened == [str(target)]


def test_power_actions_never_use_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> None:
        calls.append((command, kwargs))

    monkeypatch.setattr(system.subprocess, "run", fake_run)

    assert not system.execute_power_action(context(power_enabled=False), kind="shutdown").success
    assert not system.execute_power_action(context(), kind="unknown").success
    assert system.execute_power_action(context(), kind="restart").success
    assert calls[0][0] == ["shutdown", "/r", "/t", "0"]
    assert calls[0][1]["shell"] is False


def test_system_command_failures_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("safe-mock", 1)

    monkeypatch.setattr(system.subprocess, "run", fail)

    power = system.execute_power_action(context(), kind="sleep")
    recycle = system.empty_recycle_bin(context())
    assert not power.success
    assert power.details == "TimeoutExpired"
    assert not recycle.success
    assert recycle.details == "TimeoutExpired"
    assert not system.empty_recycle_bin(context(desktop_enabled=False)).success
