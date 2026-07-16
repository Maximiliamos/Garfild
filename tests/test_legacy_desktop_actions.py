from __future__ import annotations

import subprocess
from typing import Any

import pytest

from garfield_actions import legacy_desktop
from garfield_actions.legacy_desktop import DesktopController, invoke_controller_action
from garfield_actions.models import ActionContext


class FakeAutomation:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str):
        def call(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, args, kwargs))

        return call


@pytest.fixture
def desktop_backend(monkeypatch: pytest.MonkeyPatch) -> tuple[DesktopController, FakeAutomation]:
    automation = FakeAutomation()
    monkeypatch.setattr(legacy_desktop, "pyautogui", automation)
    monkeypatch.setattr(legacy_desktop.platform, "system", lambda: "Windows")
    monkeypatch.setattr(legacy_desktop.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(legacy_desktop.subprocess, "Popen", lambda *args, **kwargs: None)
    monkeypatch.setattr(legacy_desktop.webbrowser, "open", lambda *args, **kwargs: True)
    return DesktopController(allow_power_commands=True), automation


def test_keyboard_browser_and_window_commands_use_mocked_automation(
    desktop_backend: tuple[DesktopController, FakeAutomation],
) -> None:
    controller, automation = desktop_backend

    assert controller.browser_hotkey("new_tab")
    assert controller.browser_hotkey("unknown")
    assert controller.text_hotkey("delete_all")
    assert controller.text_hotkey("unknown")
    assert controller.navigate_text("document_start")
    assert controller.navigate_text("unknown")
    assert controller.switch_input_language()
    assert controller.minimize_windows()
    assert controller.minimize_current_window()
    assert controller.maximize_window()
    assert controller.switch_window()
    assert controller.close_window()
    assert any(name == "hotkey" for name, _, _ in automation.calls)


def test_web_mouse_audio_and_text_commands_are_mocked(
    desktop_backend: tuple[DesktopController, FakeAutomation],
) -> None:
    controller, automation = desktop_backend
    clipboard: list[str] = []
    controller._set_clipboard_text = clipboard.append  # type: ignore[method-assign]

    assert controller.open_browser()
    assert controller.search_web("safe query")
    assert controller.open_youtube()
    assert controller.open_site("Example", "https://example.test")
    assert controller.open_image_search("cats")
    assert controller.mouse_click("right")
    assert controller.mouse_double_click()
    assert controller.move_mouse("left")
    assert controller.move_mouse("unknown")
    assert controller.scroll("down")
    assert controller.type_text("hello")
    assert controller.type_text("")
    assert controller.volume_mute()
    assert controller.volume_step("up")
    assert controller.set_volume_percent(42)
    assert clipboard == ["hello"]
    assert any(name == "click" for name, _, _ in automation.calls)


def test_windows_system_helpers_use_fixed_mocked_commands(
    desktop_backend: tuple[DesktopController, FakeAutomation],
) -> None:
    controller, _ = desktop_backend

    assert controller.set_brightness_percent(55)
    assert controller.empty_recycle_bin()
    assert controller.lock_screen()
    assert controller.cancel_power_timer()
    assert controller.perform_power_action("shutdown")
    assert controller.perform_power_action("restart")
    assert controller.perform_power_action("sleep")
    assert controller.perform_power_action("unknown")
    assert DesktopController(allow_power_commands=False).perform_power_action("shutdown")


def test_missing_automation_and_action_adapter_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(legacy_desktop, "pyautogui", None)
    controller = DesktopController(allow_power_commands=False)
    assert controller.close_window()

    disabled = ActionContext("Windows", False, False)
    assert not invoke_controller_action(disabled, method_name="close_window").success

    missing = ActionContext("Windows", True, False)
    assert not invoke_controller_action(missing, method_name="close_window").success

    working = ActionContext(
        "Windows",
        True,
        False,
        metadata={"desktop_controller": controller},
    )
    assert invoke_controller_action(working, method_name="close_window").success


def test_action_adapter_reports_backend_failure() -> None:
    class BrokenController:
        def fail(self) -> str:
            raise subprocess.SubprocessError("mock failure")

    context = ActionContext(
        "Windows",
        True,
        False,
        metadata={"desktop_controller": BrokenController()},
    )
    result = invoke_controller_action(context, method_name="fail")
    assert not result.success
    assert result.details == "SubprocessError"
