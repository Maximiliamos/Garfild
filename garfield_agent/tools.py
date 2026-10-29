"""Original, narrowly scoped tool registry. No arbitrary shell/python execution."""
from __future__ import annotations

import ipaddress
import socket
import platform
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

from .storage import LocalStore


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: str
    required: tuple[str, ...] = ()


class ToolRegistry:
    SPECS = {
        "system_status": ToolSpec("system_status", "Показать версию ОС", "read"),
        "list_files": ToolSpec("list_files", "Список файлов в выделенной рабочей папке", "read"),
        "read_file": ToolSpec("read_file", "Прочитать текстовый файл из рабочей папки", "read", ("path",)),
        "recall_notes": ToolSpec("recall_notes", "Поиск личных заметок", "read"),
        "remember_note": ToolSpec("remember_note", "Сохранить заметку в локальной памяти", "write", ("text",)),
        "open_url": ToolSpec("open_url", "Открыть сайт в браузере", "external", ("url",)),
        "web_search": ToolSpec("web_search", "Открыть браузер с поиском", "external", ("query",)),
        "open_app": ToolSpec("open_app", "Открыть приложение из разрешённого списка", "system", ("name",)),
        "browser_read": ToolSpec("browser_read", "Прочитать публичную HTTPS-страницу с Playwright", "network", ("url",)),
    }
    APPS = {
        "калькулятор": ["calc.exe"],
        "calculator": ["calc.exe"],
        "блокнот": ["notepad.exe"],
        "notepad": ["notepad.exe"],
        "проводник": ["explorer.exe"],
        "explorer": ["explorer.exe"],
    }

    def __init__(self, workspace: Path, store: LocalStore):
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.store = store

    def catalogue(self) -> list[dict]:
        return [
            {"name": item.name, "description": item.description, "risk": item.risk, "required": list(item.required)}
            for item in self.SPECS.values()
        ]

    def validate(self, tool: str, args: dict) -> dict:
        spec = self.SPECS.get(tool)
        if spec is None:
            raise ValueError("Неизвестный инструмент: " + str(tool))
        if not isinstance(args, dict) or len(args) > 6:
            raise ValueError("Аргументы инструмента должны быть объектом")
        for key in spec.required:
            if not isinstance(args.get(key), str) or not args[key].strip():
                raise ValueError(f"Не указан обязательный параметр {key}")
        if set(args) - (set(spec.required) | {"path", "query", "name", "url", "text"}):
            raise ValueError("Неизвестные аргументы инструмента")
        if any(not isinstance(value, str) or len(value) > 4000 for value in args.values()):
            raise ValueError("Неверная длина или тип аргумента")
        if tool in {"open_url", "browser_read"}:
            self._validate_url(args["url"], strict=(tool == "browser_read"))
        if tool == "open_app" and args["name"].lower().strip() not in self.APPS:
            raise ValueError("Приложение отсутствует в белом списке")
        if tool == "read_file":
            self._within_workspace(args["path"])
        return args

    @staticmethod
    def _validate_url(url: str, strict: bool = False) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in ({"https"} if strict else {"https", "http"}):
            raise ValueError("Недопустимая схема URL")
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Неверный адрес сайта")
        host = parsed.hostname.strip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError("Локальные адреса запрещены")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            # Do not allow direct IP URLs, even public ones, in automated browsing.
            raise ValueError("Используйте доменное имя публичного сайта")

    def _within_workspace(self, raw: str) -> Path:
        target = (self.workspace / raw).resolve()
        if not target.is_relative_to(self.workspace):
            raise PermissionError("Доступ возможен только к файлам выделенной папки")
        if any(part.startswith(".") for part in target.relative_to(self.workspace).parts):
            raise PermissionError("Скрытые файлы не читаются")
        return target

    def execute(self, tool: str, args: dict) -> str:
        self.validate(tool, args)
        if tool == "system_status":
            return platform.platform()
        if tool == "list_files":
            root = self._within_workspace(args.get("path", "."))
            if not root.is_dir():
                raise NotADirectoryError(root)
            return "\n".join(sorted(f.name + ("/" if f.is_dir() else "") for f in root.iterdir() if not f.name.startswith("."))[:50]) or "Папка пуста"
        if tool == "read_file":
            path = self._within_workspace(args["path"])
            if path.suffix.lower() not in {".txt", ".md", ".json", ".csv", ".py", ".log"}:
                raise ValueError("Разрешены только текстовые файлы")
            if path.stat().st_size > 64_000:
                raise ValueError("Файл слишком большой")
            return path.read_text(encoding="utf-8")[:8000]
        if tool == "recall_notes":
            return str(self.store.notes(args.get("query", ""), limit=10))
        if tool == "remember_note":
            return f"Заметка сохранена под номером {self.store.add_note(args['text'])}"
        if tool == "open_url":
            webbrowser.open(args["url"])
            return "Ссылка открыта в браузере"
        if tool == "web_search":
            webbrowser.open("https://www.google.com/search?q=" + quote_plus(args["query"]))
            return "Поиск открыт в браузере"
        if tool == "open_app":
            if platform.system() != "Windows":
                raise RuntimeError("Запуск системных приложений доступен только в Windows")
            subprocess.Popen(self.APPS[args["name"].lower().strip()], shell=False)
            return "Приложение запущено"
        if tool == "browser_read":
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as error:
                raise RuntimeError("Установите playwright и выполните playwright install chromium") from error
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    def guard(route):
                        try:
                            self._validate_url(route.request.url, strict=True)
                            host = urlsplit(route.request.url).hostname
                            # Deny DNS names resolving to private/local networks.
                            addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
                            if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
                                raise ValueError("Private network address")
                        except (ValueError, OSError):
                            route.abort()
                        else:
                            route.continue_()
                    page.route("**/*", guard)
                    page.goto(args["url"], wait_until="domcontentloaded", timeout=15000)
                    self._validate_url(page.url, strict=True)
                    return page.locator("body").inner_text(timeout=5000)[:5000]
                finally:
                    browser.close()
        raise ValueError("Неизвестный инструмент")
