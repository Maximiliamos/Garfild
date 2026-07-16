from __future__ import annotations

import platform
import subprocess
import webbrowser
from collections.abc import Callable
from typing import Any
from urllib.parse import quote_plus

from .models import ActionContext, ActionResult

try:
    import pyautogui as _pyautogui
except ImportError:
    pyautogui = None
else:
    pyautogui: Any = _pyautogui


class DesktopController:
    def __init__(self, allow_power_commands: bool) -> None:
        self.allow_power_commands = allow_power_commands

    def _require_pyautogui(self) -> str | None:
        if pyautogui is None:
            return "Команда недоступна, потому что не установлен pyautogui."
        return None

    def _hotkey(self, *keys: str) -> str | None:
        error = self._require_pyautogui()
        if error:
            return error
        pyautogui.hotkey(*keys)
        return None

    def _press(self, key: str, presses: int = 1) -> str | None:
        error = self._require_pyautogui()
        if error:
            return error
        pyautogui.press(key, presses=presses, interval=0.03)
        return None

    def _set_clipboard_text(self, text: str) -> None:
        if platform.system() == "Windows":
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "param([string]$Text) Set-Clipboard -Value $Text",
                    text,
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )
            return

        try:
            import tkinter as tk
        except ImportError as error:
            raise RuntimeError("Буфер обмена недоступен: нет tkinter.") from error

        root = tk.Tk()
        root.withdraw()
        try:
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
        finally:
            root.destroy()

    def open_browser(self) -> str:
        webbrowser.open("https://www.google.com")
        return "Открываю браузер."

    def search_web(self, query: str) -> str:
        webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
        return f"Ищу в интернете: {query}."

    def open_youtube(self) -> str:
        webbrowser.open("https://www.youtube.com")
        return "Открываю YouTube."

    def open_site(self, label: str, url: str) -> str:
        webbrowser.open(url)
        return f"Открываю {label}."

    def browser_hotkey(self, action: str) -> str:
        shortcuts = {
            "new_tab": (("ctrl", "t"), "Открываю новую вкладку."),
            "close_tab": (("ctrl", "w"), "Закрываю вкладку."),
            "restore_tab": (("ctrl", "shift", "t"), "Возвращаю закрытую вкладку."),
            "next_tab": (("ctrl", "tab"), "Перехожу на следующую вкладку."),
            "previous_tab": (("ctrl", "shift", "tab"), "Перехожу на предыдущую вкладку."),
            "refresh": (("ctrl", "r"), "Обновляю страницу."),
            "downloads": (("ctrl", "j"), "Открываю загрузки."),
            "history": (("ctrl", "h"), "Открываю историю браузера."),
            "bookmarks": (("ctrl", "shift", "o"), "Открываю закладки."),
            "add_bookmark": (("ctrl", "d"), "Добавляю страницу в закладки."),
            "find_page": (("ctrl", "f"), "Открываю поиск по странице."),
            "address_bar": (("ctrl", "l"), "Перехожу в адресную строку."),
            "clear_history": (("ctrl", "shift", "delete"), "Открываю очистку истории браузера."),
        }
        if action not in shortcuts:
            return "Неизвестное действие браузера."
        keys, message = shortcuts[action]
        error = self._hotkey(*keys)
        return error or message

    def open_image_search(self, query: str) -> str:
        webbrowser.open(f"https://www.google.com/search?tbm=isch&q={quote_plus(query)}")
        return f"Ищу изображения: {query}."

    def minimize_windows(self) -> str:
        error = self._require_pyautogui()
        if error:
            return error

        if platform.system() == "Windows":
            pyautogui.hotkey("win", "d")
        elif platform.system() == "Darwin":
            pyautogui.hotkey("command", "option", "h")
        else:
            pyautogui.hotkey("win", "d")

        return "Сворачиваю окна."

    def minimize_current_window(self) -> str:
        error = self._require_pyautogui()
        if error:
            return error

        if platform.system() == "Darwin":
            pyautogui.hotkey("command", "m")
        else:
            pyautogui.hotkey("win", "down")
        return "Сворачиваю текущее окно."

    def maximize_window(self) -> str:
        error = self._require_pyautogui()
        if error:
            return error

        if platform.system() == "Darwin":
            pyautogui.hotkey("ctrl", "command", "f")
        else:
            pyautogui.hotkey("win", "up")
        return "Разворачиваю окно."

    def switch_window(self) -> str:
        error = self._require_pyautogui()
        if error:
            return error

        if platform.system() == "Darwin":
            pyautogui.hotkey("command", "tab")
        else:
            pyautogui.hotkey("alt", "tab")
        return "Переключаю окно."

    def close_window(self) -> str:
        error = self._require_pyautogui()
        if error:
            return error

        if platform.system() == "Darwin":
            pyautogui.hotkey("command", "q")
        else:
            pyautogui.hotkey("alt", "f4")

        return "Закрываю текущее окно."

    def mouse_click(self, button: str = "left") -> str:
        error = self._require_pyautogui()
        if error:
            return error
        pyautogui.click(button=button)
        return "Кликаю правой кнопкой." if button == "right" else "Кликаю левой кнопкой."

    def mouse_double_click(self) -> str:
        error = self._require_pyautogui()
        if error:
            return error
        pyautogui.doubleClick()
        return "Двойной клик."

    def move_mouse(self, direction: str, amount: int = 80) -> str:
        error = self._require_pyautogui()
        if error:
            return error
        offsets = {
            "left": (-amount, 0, "Перемещаю курсор влево."),
            "right": (amount, 0, "Перемещаю курсор вправо."),
            "up": (0, -amount, "Перемещаю курсор вверх."),
            "down": (0, amount, "Перемещаю курсор вниз."),
        }
        if direction not in offsets:
            return "Неизвестное направление курсора."
        x, y, message = offsets[direction]
        pyautogui.moveRel(x, y, duration=0.12)
        return message

    def scroll(self, direction: str, amount: int = 5) -> str:
        error = self._require_pyautogui()
        if error:
            return error
        clicks = amount if direction == "up" else -amount
        pyautogui.scroll(clicks)
        return "Прокручиваю вверх." if direction == "up" else "Прокручиваю вниз."

    def text_hotkey(self, action: str) -> str:
        shortcuts = {
            "copy": (("ctrl", "c"), "Копирую текст."),
            "cut": (("ctrl", "x"), "Вырезаю текст."),
            "paste": (("ctrl", "v"), "Вставляю текст."),
            "select_all": (("ctrl", "a"), "Выделяю весь текст."),
            "delete_all": (("ctrl", "a"), "Удаляю весь текст.", "backspace"),
            "delete_last_word": (("ctrl", "backspace"), "Удаляю последнее слово."),
            "send": (("enter",), "Отправляю."),
            "undo": (("ctrl", "z"), "Отменяю последнее действие."),
            "save_as": (("ctrl", "shift", "s"), "Открываю сохранение как."),
            "align_left": (("ctrl", "l"), "Выравниваю по левому краю."),
            "align_center": (("ctrl", "e"), "Выравниваю по центру."),
            "align_right": (("ctrl", "r"), "Выравниваю по правому краю."),
            "align_justify": (("ctrl", "j"), "Выравниваю по ширине."),
        }
        if action not in shortcuts:
            return "Неизвестное действие текста."
        payload = shortcuts[action]
        keys = payload[0]
        message = payload[1]
        error = self._hotkey(*keys)
        if error:
            return error
        if len(payload) > 2:
            pyautogui.press(payload[2])
        return message

    def navigate_text(self, action: str) -> str:
        shortcuts = {
            "line_start": (("home",), "Перехожу в начало строки."),
            "line_end": (("end",), "Перехожу в конец строки."),
            "document_start": (("ctrl", "home"), "Перехожу в начало документа."),
            "document_end": (("ctrl", "end"), "Перехожу в конец документа."),
            "up": (("up",), "Перемещаю курсор вверх."),
            "down": (("down",), "Перемещаю курсор вниз."),
            "left": (("left",), "Перемещаю курсор влево."),
            "right": (("right",), "Перемещаю курсор вправо."),
        }
        if action not in shortcuts:
            return "Неизвестная навигационная команда."
        keys, message = shortcuts[action]
        error = self._press(keys[0]) if len(keys) == 1 else self._hotkey(*keys)
        return error or message

    def type_text(self, text: str) -> str:
        error = self._require_pyautogui()
        if error:
            return error
        if not text:
            return "Не услышал текст для ввода."
        self._set_clipboard_text(text)
        pyautogui.hotkey("ctrl", "v")
        return f"Ввожу текст: {text}."

    def switch_input_language(self) -> str:
        error = self._require_pyautogui()
        if error:
            return error
        if platform.system() == "Windows":
            pyautogui.hotkey("alt", "shift")
        elif platform.system() == "Darwin":
            pyautogui.hotkey("control", "space")
        else:
            pyautogui.hotkey("alt", "shift")
        return "Меняю язык ввода."

    def volume_mute(self) -> str:
        error = self._press("volumemute")
        return error or "Переключаю режим без звука."

    def volume_step(self, direction: str, presses: int = 5) -> str:
        key = "volumeup" if direction == "up" else "volumedown"
        error = self._press(key, presses=presses)
        return error or ("Увеличиваю громкость." if direction == "up" else "Уменьшаю громкость.")

    def set_volume_percent(self, percent: int) -> str:
        percent = max(0, min(int(percent), 100))
        error = self._require_pyautogui()
        if error:
            return error
        pyautogui.press("volumedown", presses=50, interval=0.01)
        if percent > 0:
            pyautogui.press("volumeup", presses=max(1, round(percent / 2)), interval=0.01)
        return f"Ставлю громкость примерно на {percent}%."

    def set_brightness_percent(self, percent: int) -> str:
        percent = max(0, min(int(percent), 100))
        if platform.system() != "Windows":
            return "Управление яркостью сейчас доступно только на Windows."
        command = (
            f"$Brightness = {percent}; "
            "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods) "
            "| ForEach-Object { $_.WmiSetBrightness(1, $Brightness) }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            timeout=10,
        )
        return f"Ставлю яркость на {percent}%."

    def empty_recycle_bin(self) -> str:
        if platform.system() != "Windows":
            return "Очистка корзины поддерживается только на Windows."
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
            check=False,
            capture_output=True,
            timeout=20,
        )
        return "Корзина очищена."

    def lock_screen(self) -> str:
        if platform.system() == "Windows":
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
            return "Блокирую экран."
        error = (
            self._hotkey("ctrl", "command", "q") if platform.system() == "Darwin" else self._hotkey("ctrl", "alt", "l")
        )
        return error or "Блокирую экран."

    def cancel_power_timer(self) -> str:
        if platform.system() == "Windows":
            subprocess.run(
                ["shutdown", "/a"],
                check=False,
                capture_output=True,
                timeout=10,
                shell=False,
            )
            return "Отменяю запланированное выключение или перезагрузку."
        return "Отмена таймера питания поддерживается только на Windows."

    def perform_power_action(self, kind: str) -> str:
        if not self.allow_power_commands:
            return "Силовые команды отключены в конфиге ради безопасности."

        if kind == "shutdown":
            if platform.system() == "Windows":
                command = ["shutdown", "/s", "/t", "15"]
            elif platform.system() == "Darwin":
                command = ["sudo", "shutdown", "-h", "+1"]
            else:
                command = ["shutdown", "-h", "+1"]
            subprocess.run(command, check=False, capture_output=True, timeout=10, shell=False)
            return "Подтверждение принято. Компьютер будет выключен через короткое время."

        if kind == "restart":
            if platform.system() == "Windows":
                command = ["shutdown", "/r", "/t", "15"]
            elif platform.system() == "Darwin":
                command = ["sudo", "shutdown", "-r", "+1"]
            else:
                command = ["shutdown", "-r", "+1"]
            subprocess.run(command, check=False, capture_output=True, timeout=10, shell=False)
            return "Подтверждение принято. Компьютер будет перезагружен через короткое время."

        if kind == "sleep":
            if platform.system() == "Windows":
                subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
            elif platform.system() == "Darwin":
                subprocess.run(["pmset", "sleepnow"], check=False, timeout=10, shell=False)
            else:
                subprocess.run(["systemctl", "suspend"], check=False, timeout=10, shell=False)
            return "Подтверждение принято. Перевожу компьютер в спящий режим."

        return "Неизвестное действие питания."


def invoke_controller_action(
    context: ActionContext,
    *,
    method_name: str,
    **arguments: object,
) -> ActionResult:
    if not context.desktop_enabled:
        return ActionResult(False, "Desktop-команды отключены в конфигурации.")
    controller = context.metadata.get("desktop_controller")
    method = getattr(controller, method_name, None)
    if not isinstance(method, Callable):
        return ActionResult(False, "Desktop-команда недоступна.")
    try:
        message = method(**arguments)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return ActionResult(False, "Desktop-команда не выполнена.", details=type(error).__name__)
    return ActionResult(True, str(message))
