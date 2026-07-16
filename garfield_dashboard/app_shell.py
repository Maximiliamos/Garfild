"""Main application shell for the modern Garfield dashboard."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import threading
import tkinter as tk
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk

from .components import ConfirmDialog, StatusPill
from .pages.audio import AudioPage
from .pages.chat import ChatPage
from .pages.commands import CommandsPage
from .pages.diagnostics import DiagnosticsPage
from .pages.history import HistoryPage
from .pages.settings import SettingsPage
from .pages.skills import SkillsPage
from .pages.voice import VoicePage
from .services import DashboardPaths, RuntimeAdapter
from .sidebar import Sidebar
from .theme import APP_TITLE, COLORS, FONTS


PAGE_META = {
    "chat": ("Чат", "Диалог, быстрые команды и live-журнал ассистента."),
    "commands": ("Команды", "Каталог встроенных голосовых сценариев."),
    "voice": ("Голос", "Прослушивание, wake word и шумовой порог."),
    "audio": ("Звук", "Микрофон, устройство вывода и тесты аудио."),
    "skills": ("Навыки", "Локальные команды и действия ассистента."),
    "diagnostics": ("Диагностика", "Состояние моделей, API, памяти и устройств."),
    "settings": ("Настройки", "Конфиг приложения, модели и API."),
    "history": ("История", "Сообщения текущей сессии, фильтры и экспорт."),
}


class CatLauncher:
    """Small always-on-top launcher that sits above the Windows clock."""

    def __init__(self, app: "DashboardApp", on_open: Callable[[], None]) -> None:
        self.app = app
        self.on_open = on_open
        self.size = 76
        self.window = ctk.CTkToplevel(app)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.resizable(False, False)
        self.window.configure(fg_color=COLORS["background"])
        self._set_window_flags()
        self._build()
        self.reposition()

    def _set_window_flags(self) -> None:
        try:
            self.window.attributes("-topmost", True)
        except tk.TclError:
            pass
        if os.name == "nt":
            try:
                self.window.attributes("-toolwindow", True)
            except tk.TclError:
                pass

    def _build(self) -> None:
        self.container = ctk.CTkFrame(
            self.window,
            width=self.size,
            height=self.size,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
        )
        self.container.grid(row=0, column=0, sticky="nsew")
        self.container.grid_propagate(False)

        self.canvas = tk.Canvas(
            self.container,
            width=58,
            height=54,
            bg=COLORS["surface"],
            highlightthickness=0,
            bd=0,
        )
        self.canvas.grid(row=0, column=0, padx=9, pady=(9, 0))
        self._draw_cat()

        self.status_dot = ctk.CTkLabel(
            self.container,
            text="",
            width=10,
            height=10,
            fg_color=COLORS["success"],
            corner_radius=5,
        )
        self.status_dot.place(x=55, y=54)

        for widget in (self.window, self.container, self.canvas, self.status_dot):
            widget.bind("<Button-1>", self._open)
            widget.bind("<Enter>", self._hover)
            widget.bind("<Leave>", self._normal)

    def _draw_cat(self) -> None:
        orange = "#F59E0B"
        orange_dark = "#B45309"
        cream = "#FFE7B8"
        eye = "#111417"

        self.canvas.create_polygon(12, 20, 17, 4, 27, 19, fill=orange, outline=orange_dark, width=2)
        self.canvas.create_polygon(31, 19, 41, 4, 46, 20, fill=orange, outline=orange_dark, width=2)
        self.canvas.create_oval(8, 13, 50, 51, fill=orange, outline=orange_dark, width=2)
        self.canvas.create_oval(17, 30, 41, 51, fill=cream, outline=cream)
        self.canvas.create_oval(18, 24, 24, 31, fill=eye, outline=eye)
        self.canvas.create_oval(34, 24, 40, 31, fill=eye, outline=eye)
        self.canvas.create_polygon(27, 33, 31, 33, 29, 36, fill="#F43F5E", outline="#F43F5E")
        self.canvas.create_line(29, 36, 29, 41, fill=eye, width=2)
        self.canvas.create_line(9, 35, 23, 37, fill=cream, width=2)
        self.canvas.create_line(9, 41, 23, 40, fill=cream, width=2)
        self.canvas.create_line(35, 37, 49, 35, fill=cream, width=2)
        self.canvas.create_line(35, 40, 49, 41, fill=cream, width=2)

    def _open(self, _event: tk.Event | None = None) -> None:
        self.on_open()

    def _hover(self, _event: tk.Event | None = None) -> None:
        self.container.configure(border_color=COLORS["accent"], fg_color=COLORS["surface_alt"])
        self.canvas.configure(bg=COLORS["surface_alt"])

    def _normal(self, _event: tk.Event | None = None) -> None:
        self.container.configure(border_color=COLORS["border"], fg_color=COLORS["surface"])
        self.canvas.configure(bg=COLORS["surface"])

    def _work_area(self) -> tuple[int, int, int, int]:
        if os.name == "nt":
            try:
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
                return rect.left, rect.top, rect.right, rect.bottom
            except Exception:
                pass
        return 0, 0, self.app.winfo_screenwidth(), self.app.winfo_screenheight()

    def reposition(self) -> None:
        left, top, right, bottom = self._work_area()
        x = max(left, right - self.size - 18)
        y = max(top, bottom - self.size - 18)
        self.window.geometry(f"{self.size}x{self.size}+{x}+{y}")

    def show(self) -> None:
        self.reposition()
        self.window.deiconify()
        self.window.lift()
        self._set_window_flags()

    def hide(self) -> None:
        self.window.withdraw()

    def destroy(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()


class DashboardApp(ctk.CTk):
    def __init__(
        self,
        runtime: Any,
        *,
        save_config: Callable[[Any], None],
        paths: DashboardPaths,
    ) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.adapter = RuntimeAdapter(runtime, save_config=save_config, paths=paths)
        self.is_closing = False
        self.current_status = "Инициализация..."
        self.current_page_key = "chat"
        self.event_history: list[Any] = []
        self._last_voice_state: tuple[bool, bool] | None = None
        self.main_window_visible = False

        self.title(APP_TITLE)
        self.geometry("1280x780")
        self.minsize(1100, 720)
        self.configure(fg_color=COLORS["background"])

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = Sidebar(
            self,
            self.navigate,
            self.request_listening_toggle,
            self.toggle_tts,
            self.toggle_voice_bundle,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsw")

        content = ctk.CTkFrame(self, fg_color=COLORS["background"], corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(content, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 12))
        header.grid_columnconfigure(0, weight=1)

        self.page_title = ctk.CTkLabel(
            header,
            text="Чат",
            anchor="w",
            text_color=COLORS["text"],
            font=FONTS["display"],
        )
        self.page_title.grid(row=0, column=0, sticky="ew")
        self.page_subtitle = ctk.CTkLabel(
            header,
            text="Диалог, быстрые команды и live-журнал ассистента.",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["body"],
        )
        self.page_subtitle.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.notice = StatusPill(header, "Инициализация", "warning", width=360)
        self.notice.grid(row=0, column=1, rowspan=2, sticky="e", padx=(18, 0))

        self.page_container = ctk.CTkFrame(content, fg_color="transparent")
        self.page_container.grid(row=1, column=0, sticky="nsew", padx=22, pady=(0, 22))
        self.page_container.grid_columnconfigure(0, weight=1)
        self.page_container.grid_rowconfigure(0, weight=1)

        self.page_classes: dict[str, type] = {
            "chat": ChatPage,
            "commands": CommandsPage,
            "voice": VoicePage,
            "audio": AudioPage,
            "skills": SkillsPage,
            "diagnostics": DiagnosticsPage,
            "settings": SettingsPage,
            "history": HistoryPage,
        }
        self.pages: dict[str, Any] = {}

        self.protocol("WM_DELETE_WINDOW", self.hide_to_cat)
        self.navigate("chat")
        self.cat_launcher = CatLauncher(self, self.show_main_window)
        self.bind("<Unmap>", self._handle_unmap, add="+")
        self.hide_to_cat()
        self.after(120, self._preload_pages)

    def run(self) -> None:
        self.adapter.start()
        self._poll_events()
        try:
            self.mainloop()
        except tk.TclError:
            if not self.is_closing:
                raise

    def navigate(self, page_key: str) -> None:
        if page_key not in self.page_classes:
            return
        title, subtitle = PAGE_META[page_key]
        page = self._get_page(page_key)
        self.page_title.configure(text=title)
        self.page_subtitle.configure(text=subtitle)
        self.sidebar.set_active(page_key)
        self.current_page_key = page_key
        page.grid(row=0, column=0, sticky="nsew")
        page.tkraise()
        for key, existing_page in self.pages.items():
            if key != page_key:
                existing_page.grid_remove()
        self.after_idle(lambda key=page_key: self._after_navigate(key))

    def _after_navigate(self, page_key: str) -> None:
        if page_key != self.current_page_key:
            return
        self._refresh_page_state(page_key)
        page = self.pages.get(page_key)
        on_show = getattr(page, "on_show", None)
        if callable(on_show):
            on_show()

    def _preload_pages(self) -> None:
        if self.is_closing:
            return
        for page_key in self.page_classes:
            self._get_page(page_key)
        active_page = self.pages.get(self.current_page_key)
        if active_page:
            active_page.grid(row=0, column=0, sticky="nsew")
            active_page.tkraise()

    def _get_page(self, page_key: str) -> Any:
        if page_key not in self.pages:
            page = self.page_classes[page_key](self.page_container, self.adapter, self)
            page.grid(row=0, column=0, sticky="nsew")
            page.grid_remove()
            self.pages[page_key] = page
            if page_key == "history":
                for event in self.event_history:
                    page.add_event(event)
        return self.pages[page_key]

    def _refresh_page_state(self, page_key: str | None = None) -> None:
        if page_key:
            targets = [self.pages[page_key]] if page_key in self.pages else []
        else:
            targets = [self.pages[self.current_page_key]] if self.current_page_key in self.pages else []
        for page in targets:
            updater = getattr(page, "update_state", None)
            if callable(updater):
                try:
                    updater()
                except Exception as error:
                    logging.debug("Не удалось обновить состояние страницы: %s", error)

    def _poll_events(self) -> None:
        events = self.adapter.drain_events()
        for event in events:
            self._handle_event(event)

        if self.adapter.runtime.stop_event.is_set():
            self.show_notice("Ассистент остановлен.", "muted")
            if not self.is_closing:
                self.after(120, self._finalize_close)
            return

        if events:
            self._refresh_page_state()
            self._update_sidebar_voice_state()
        self.after(300, self._poll_events)

    def _handle_event(self, event: Any) -> None:
        kind = getattr(event, "kind", "")
        text = getattr(event, "text", "")
        self.event_history.append(event)
        if kind == "status":
            self.current_status = text
            self.show_notice(text, "info")
        elif kind == "progress":
            self.show_notice(text, "warning")
        elif kind == "assistant":
            self.sidebar.set_status("Ассистент активен", "success")
            self.show_notice("Готов. Ожидаю команду.", "success")

        self._get_page("chat").add_event(event)
        if "history" in self.pages:
            self.pages["history"].add_event(event)

    def show_notice(self, text: str, tone: str = "info") -> None:
        if not getattr(self.adapter.config, "screen_hints_enabled", True) and tone != "danger":
            return
        self.notice.set(text, tone)
        if tone in {"success", "warning", "danger"}:
            self.sidebar.set_status(text[:32], tone)

    def request_listening_toggle(self) -> None:
        target = not self.adapter.runtime.listening_enabled
        self.show_notice("Переключаю прослушивание...", "warning")
        self.run_async(
            lambda: self.adapter.set_listening(target),
            on_success=lambda _result: self._after_voice_toggle(),
            on_error=lambda error: self.show_notice(f"Не удалось переключить прослушивание: {error}", "danger"),
        )

    def _after_voice_toggle(self) -> None:
        self._refresh_page_state()
        self._update_sidebar_voice_state()

    def toggle_tts(self) -> None:
        self.adapter.runtime.tts.enabled = not self.adapter.runtime.tts.enabled
        self.adapter.runtime.config.tts_enabled = self.adapter.runtime.tts.enabled
        self.adapter.save_current_config()
        self.adapter.log_action("Озвучка включена." if self.adapter.runtime.tts.enabled else "Озвучка выключена.")
        self._refresh_page_state()
        self._update_sidebar_voice_state()

    def toggle_voice_bundle(self) -> None:
        enable = not (self.adapter.runtime.listening_enabled and self.adapter.runtime.tts.enabled)
        self.adapter.runtime.tts.enabled = enable
        self.adapter.runtime.config.tts_enabled = enable
        self.adapter.save_current_config()
        self.adapter.log_action("Голосовой блок включается." if enable else "Голосовой блок выключается.")
        self.run_async(
            lambda: self.adapter.set_listening(enable),
            on_success=lambda _result: self._after_voice_toggle(),
            on_error=lambda error: self.show_notice(f"Не удалось переключить голосовой блок: {error}", "danger"),
        )

    def _update_sidebar_voice_state(self) -> None:
        state = (bool(self.adapter.runtime.listening_enabled), bool(self.adapter.runtime.tts.enabled))
        if state == self._last_voice_state:
            return
        self._last_voice_state = state
        self.sidebar.set_voice_state(*state)

    def run_async(
        self,
        worker: Callable[[], Any],
        *,
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        def task() -> None:
            try:
                result = worker()
            except Exception as error:
                self.after(0, lambda exc=error: (on_error(exc) if on_error else self.show_notice(str(exc), "danger")))
                return
            self.after(0, lambda value=result: (on_success(value) if on_success else None))

        threading.Thread(target=task, daemon=True).start()

    def show_main_window(self) -> None:
        if self.is_closing:
            return
        self.cat_launcher.hide()
        self.main_window_visible = True
        self.deiconify()
        try:
            self.state("normal")
        except tk.TclError:
            pass
        self.lift()
        self.focus_force()
        try:
            self.attributes("-topmost", True)
            self.after(350, lambda: self.winfo_exists() and self.attributes("-topmost", False))
        except tk.TclError:
            pass
        self._refresh_page_state()
        self._update_sidebar_voice_state()

    def _handle_unmap(self, event: tk.Event) -> None:
        if event.widget is not self or self.is_closing or not self.main_window_visible:
            return
        self.after(10, self._redirect_minimize_to_cat)

    def _redirect_minimize_to_cat(self) -> None:
        if self.is_closing or not self.main_window_visible:
            return
        try:
            if self.state() == "iconic":
                self.hide_to_cat()
        except tk.TclError:
            pass

    def hide_to_cat(self) -> None:
        if self.is_closing:
            return
        self.main_window_visible = False
        self.withdraw()
        self.cat_launcher.show()

    def confirm_exit(self) -> None:
        ConfirmDialog(
            self,
            "Выход",
            "Остановить Garfield Flagship и закрыть приложение?",
            self._finalize_close,
            confirm_text="Закрыть",
            danger=True,
        )

    def _finalize_close(self) -> None:
        if self.is_closing:
            return
        self.is_closing = True
        try:
            self.cat_launcher.destroy()
            self.adapter.stop()
        except Exception as error:
            logging.warning("Ошибка остановки runtime: %s", error)
        if self.winfo_exists():
            self.after(150, self.destroy)


def run_dashboard(runtime: Any, *, save_config: Callable[[Any], None], base_dir: Path, config_path: Path, log_path: Path, session_log_path: Path) -> None:
    paths = DashboardPaths(
        base_dir=base_dir,
        config_path=config_path,
        log_path=log_path,
        session_log_path=session_log_path,
    )
    DashboardApp(runtime, save_config=save_config, paths=paths).run()
