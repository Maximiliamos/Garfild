from __future__ import annotations

import subprocess
import webbrowser
from urllib.parse import quote_plus

from .models import ActionContext, ActionResult

APPLICATIONS = {
    "calculator": ["calc.exe"],
    "notepad": ["notepad.exe"],
}


def _pyautogui():
    try:
        import pyautogui
    except ImportError:
        return None
    return pyautogui


def open_application(
    context: ActionContext,
    *,
    app_id: str,
) -> ActionResult:
    if not context.desktop_enabled:
        return ActionResult(False, "Desktop-команды отключены в конфигурации.")
    command = APPLICATIONS.get(app_id)
    if command is None:
        return ActionResult(False, "Неизвестное приложение.")
    subprocess.Popen(command, shell=False)
    return ActionResult(True, f"Открываю приложение: {app_id}.")


def close_window(context: ActionContext) -> ActionResult:
    if not context.desktop_enabled:
        return ActionResult(False, "Desktop-команды отключены в конфигурации.")
    automation = _pyautogui()
    if automation is None:
        return ActionResult(False, "Команда недоступна: pyautogui не установлен.")
    if context.platform_name == "Darwin":
        automation.hotkey("command", "q")
    else:
        automation.hotkey("alt", "f4")
    return ActionResult(True, "Закрываю текущее окно.")


def type_text(
    context: ActionContext,
    *,
    text: str,
) -> ActionResult:
    if not context.desktop_enabled:
        return ActionResult(False, "Desktop-команды отключены в конфигурации.")
    automation = _pyautogui()
    if automation is None:
        return ActionResult(False, "Команда недоступна: pyautogui не установлен.")
    if not text:
        return ActionResult(False, "Не указан текст для ввода.")

    clipboard_writer = context.metadata.get("clipboard_writer")
    if not callable(clipboard_writer):
        return ActionResult(False, "Буфер обмена недоступен.")
    clipboard_writer(text)
    automation.hotkey("ctrl", "v")
    return ActionResult(True, "Текст введён.")


def search_web(
    context: ActionContext,
    *,
    query: str,
) -> ActionResult:
    del context
    webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
    return ActionResult(True, f"Ищу в интернете: {query}.")


def open_web(
    context: ActionContext,
    *,
    url: str,
) -> ActionResult:
    del context
    webbrowser.open(url)
    return ActionResult(True, "Открываю веб-страницу.")
