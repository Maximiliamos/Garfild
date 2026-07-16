from __future__ import annotations

import subprocess

from .models import ActionContext, ActionResult

POWER_COMMANDS = {
    "shutdown": ["shutdown", "/s", "/t", "0"],
    "restart": ["shutdown", "/r", "/t", "0"],
    "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
}


def execute_power_action(
    context: ActionContext,
    *,
    kind: str,
) -> ActionResult:
    if not context.power_enabled:
        return ActionResult(False, "Силовые команды отключены в конфигурации.")
    command = POWER_COMMANDS.get(kind)
    if command is None:
        return ActionResult(False, "Неизвестная системная команда.")
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        return ActionResult(
            False,
            "Windows отклонила системную команду.",
            details=type(error).__name__,
        )
    return ActionResult(True, "Системная команда выполнена.")


def empty_recycle_bin(context: ActionContext) -> ActionResult:
    if not context.desktop_enabled:
        return ActionResult(False, "Desktop-команды отключены в конфигурации.")
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Clear-RecycleBin -Force -ErrorAction Stop",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        return ActionResult(
            False,
            "Windows отклонила очистку корзины.",
            details=type(error).__name__,
        )
    return ActionResult(True, "Корзина очищена.")
