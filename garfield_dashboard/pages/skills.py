"""Local skills management page."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from ..components import ConfirmDialog, StatusPill, action_button, card, labeled_input
from ..services import SkillRecord
from ..theme import COLORS, FONTS

SKILL_ACTIONS = ["say", "open_url", "search_web", "open_path", "run", "python", "hotkey"]


class SkillDialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str, record: SkillRecord | None, on_save: Callable[[SkillRecord], None]) -> None:
        super().__init__(parent)
        self.title(title)
        self.geometry("620x620")
        self.minsize(560, 560)
        self.configure(fg_color=COLORS["background"])
        self.transient(parent)
        self.grab_set()
        self.on_save = on_save

        record = record or SkillRecord()
        self.id_var = tk.StringVar(value=record.skill_id)
        self.action_var = tk.StringVar(value=record.action or "say")
        self.target_var = tk.StringVar(value=record.target)
        self.response_var = tk.StringVar(value=record.response)
        self.arguments_var = tk.StringVar(value=", ".join(record.arguments))
        self.use_shell_var = tk.BooleanVar(value=record.use_shell)

        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title, anchor="w", text_color=COLORS["text"], font=FONTS["title"]).grid(
            row=0,
            column=0,
            sticky="ew",
            padx=22,
            pady=(22, 12),
        )

        form = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=8, border_width=1, border_color=COLORS["border"])
        form.grid(row=1, column=0, sticky="nsew", padx=22, pady=(0, 16))
        form.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        labeled_input(form, "ID навыка", 0, self.id_var)

        ctk.CTkLabel(form, text="Действие", anchor="w", font=FONTS["body_bold"], text_color=COLORS["text"]).grid(
            row=1,
            column=0,
            sticky="w",
            padx=(14, 16),
            pady=8,
        )
        ctk.CTkOptionMenu(
            form,
            values=SKILL_ACTIONS,
            variable=self.action_var,
            fg_color=COLORS["input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            text_color=COLORS["text"],
            height=36,
            corner_radius=8,
        ).grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=8)

        ctk.CTkLabel(form, text="Фразы активации", anchor="nw", font=FONTS["body_bold"], text_color=COLORS["text"]).grid(
            row=2,
            column=0,
            sticky="nw",
            padx=(14, 16),
            pady=8,
        )
        self.phrases_text = ctk.CTkTextbox(
            form,
            height=110,
            fg_color=COLORS["input"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
            font=FONTS["body"],
        )
        self.phrases_text.grid(row=2, column=1, sticky="ew", padx=(0, 14), pady=8)
        self.phrases_text.insert("1.0", "\n".join(record.phrases))

        labeled_input(form, "Цель / target", 3, self.target_var)
        labeled_input(form, "Ответ", 4, self.response_var)
        labeled_input(form, "Аргументы", 5, self.arguments_var)

        ctk.CTkLabel(form, text="use_shell", anchor="w", font=FONTS["body_bold"], text_color=COLORS["text"]).grid(
            row=6,
            column=0,
            sticky="w",
            padx=(14, 16),
            pady=8,
        )
        ctk.CTkSwitch(form, text="", variable=self.use_shell_var, progress_color=COLORS["accent"]).grid(
            row=6,
            column=1,
            sticky="w",
            padx=(0, 14),
            pady=8,
        )

        self.error_label = ctk.CTkLabel(self, text="", anchor="w", text_color=COLORS["danger"], font=FONTS["small"])
        self.error_label.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 8))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew", padx=22, pady=(0, 22))
        buttons.grid_columnconfigure(0, weight=1)
        action_button(buttons, "Отмена", self.destroy, tone="ghost", width=110).grid(row=0, column=1, padx=(0, 10))
        action_button(buttons, "Сохранить", self._save, width=130).grid(row=0, column=2)

    def _save(self) -> None:
        phrases = [line.strip() for line in self.phrases_text.get("1.0", "end").replace(",", "\n").splitlines() if line.strip()]
        skill_id = self.id_var.get().strip()
        action = self.action_var.get().strip()
        if not skill_id:
            self.error_label.configure(text="Укажите ID навыка.")
            return
        if not phrases:
            self.error_label.configure(text="Добавьте хотя бы одну фразу активации.")
            return
        if action not in SKILL_ACTIONS:
            self.error_label.configure(text="Выберите корректное действие.")
            return

        record = SkillRecord(
            skill_id=skill_id,
            phrases=phrases,
            action=action,
            target=self.target_var.get().strip(),
            response=self.response_var.get().strip(),
            arguments=[item.strip() for item in self.arguments_var.get().split(",") if item.strip()],
            use_shell=bool(self.use_shell_var.get()),
        )
        self.destroy()
        self.on_save(record)


class SkillsPage(ctk.CTkFrame):
    def __init__(self, parent, adapter, app) -> None:
        super().__init__(parent, fg_color="transparent")
        self.adapter = adapter
        self.app = app
        self.records: list[SkillRecord] = []
        self.selected_index: int | None = None
        self.rows: list[ctk.CTkFrame] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = card(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Навыки", anchor="w", text_color=COLORS["text"], font=FONTS["title"]).grid(
            row=0,
            column=0,
            sticky="ew",
            padx=18,
            pady=(16, 2),
        )
        self.status = StatusPill(top, "Навыки не загружены", "muted")
        self.status.grid(row=0, column=1, sticky="e", padx=18, pady=16)
        ctk.CTkLabel(
            top,
            text="Локальные команды, которые расширяют возможности ассистента.",
            anchor="w",
            text_color=COLORS["text_secondary"],
            font=FONTS["body"],
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))

        table_card = card(self)
        table_card.grid(row=1, column=0, sticky="nsew")
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(table_card, fg_color=COLORS["surface_alt"], corner_radius=8)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        widths = [92, 180, 82, 150, 170]
        labels = ["ID навыка", "Фразы активации", "Действие", "Цель / target", "Ответ"]
        for col, label in enumerate(labels):
            header.grid_columnconfigure(col, weight=1, minsize=widths[col])
            ctk.CTkLabel(header, text=label, anchor="w", text_color=COLORS["text_secondary"], font=FONTS["small"]).grid(
                row=0,
                column=col,
                sticky="ew",
                padx=10,
                pady=9,
            )

        self.table = ctk.CTkScrollableFrame(table_card, fg_color=COLORS["surface"], corner_radius=8)
        self.table.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        for col in range(5):
            self.table.grid_columnconfigure(col, weight=1, minsize=widths[col])

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        for index in range(3):
            actions.grid_columnconfigure(index, weight=1)
        buttons = [
            ("Обновить навыки", self.reload_skills, "ghost"),
            ("Открыть файл навыков", self.open_skills_file, "ghost"),
            ("Добавить навык", self.add_skill, "primary"),
            ("Редактировать", self.edit_skill, "ghost"),
            ("Удалить", self.delete_skill, "danger"),
        ]
        for index, (text, command, tone) in enumerate(buttons):
            action_button(actions, text, command, tone=tone, width=128).grid(
                row=index // 3,
                column=index % 3,
                sticky="ew",
                padx=4,
                pady=4,
            )

        self.refresh()

    def refresh(self) -> None:
        self.records = self.adapter.skill_records()
        self.selected_index = None
        for row in self.rows:
            row.destroy()
        self.rows = []

        for index, record in enumerate(self.records):
            self._add_row(index, record)
        self.status.set(f"Активно {len(self.records)} навыков", "success" if self.records else "warning")

    def _add_row(self, index: int, record: SkillRecord) -> None:
        row = ctk.CTkFrame(self.table, fg_color=COLORS["surface_alt"], corner_radius=8)
        row.grid(row=index, column=0, columnspan=5, sticky="ew", pady=3)
        for col in range(5):
            row.grid_columnconfigure(col, weight=1)
        values = [
            record.skill_id,
            "; ".join(record.phrases),
            record.action,
            record.target,
            record.response,
        ]
        for col, value in enumerate(values):
            label = ctk.CTkLabel(
                row,
                text=value or "—",
                anchor="w",
                justify="left",
                text_color=COLORS["text"],
                font=FONTS["small"],
                wraplength=[92, 180, 82, 150, 170][col],
            )
            label.grid(row=0, column=col, sticky="ew", padx=10, pady=9)
            label.bind("<Button-1>", lambda _event, item=index: self.select_row(item))
        row.bind("<Button-1>", lambda _event, item=index: self.select_row(item))
        self.rows.append(row)

    def select_row(self, index: int) -> None:
        self.selected_index = index
        for row_index, row in enumerate(self.rows):
            row.configure(fg_color=COLORS["accent_soft"] if row_index == index else COLORS["surface_alt"])

    def reload_skills(self) -> None:
        try:
            message = self.adapter.reload_skills()
            self.refresh()
            self.app.show_notice(message, "success")
            self.adapter.log_action("Навыки обновлены через интерфейс.")
        except Exception as error:
            self.app.show_notice(f"Не удалось обновить навыки: {error}", "danger")

    def open_skills_file(self) -> None:
        try:
            message = self.adapter.open_skills_file()
            self.app.show_notice(message, "success")
            self.adapter.log_action("Открыт файл навыков.")
        except Exception as error:
            self.app.show_notice(f"Не удалось открыть файл навыков: {error}", "danger")

    def add_skill(self) -> None:
        SkillDialog(self, "Добавить навык", None, self._append_skill)

    def _append_skill(self, record: SkillRecord) -> None:
        self.records.append(record)
        self._save_records("Навык добавлен.")

    def edit_skill(self) -> None:
        if self.selected_index is None:
            self.app.show_notice("Выберите навык для редактирования.", "warning")
            return
        SkillDialog(self, "Редактировать навык", self.records[self.selected_index], self._replace_selected)

    def _replace_selected(self, record: SkillRecord) -> None:
        if self.selected_index is None:
            return
        self.records[self.selected_index] = record
        self._save_records("Навык обновлен.")

    def delete_skill(self) -> None:
        if self.selected_index is None:
            self.app.show_notice("Выберите навык для удаления.", "warning")
            return

        def remove() -> None:
            if self.selected_index is None:
                return
            self.records.pop(self.selected_index)
            self._save_records("Навык удален.")

        ConfirmDialog(self, "Удалить навык", "Удалить выбранный навык из файла навыков?", remove, confirm_text="Удалить", danger=True)

    def _save_records(self, notice: str) -> None:
        try:
            message = self.adapter.save_skill_records(self.records)
            self.refresh()
            self.app.show_notice(f"{notice} {message}", "success")
            self.adapter.log_action(notice)
        except Exception as error:
            self.app.show_notice(f"Не удалось сохранить навыки: {error}", "danger")
