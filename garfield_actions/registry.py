from __future__ import annotations

from functools import partial

from garfield_intents import RiskLevel

from .desktop import (
    close_window,
    open_application,
    open_project_file,
    open_web,
    search_web,
    type_text,
)
from .legacy_desktop import invoke_controller_action
from .models import ActionContext, ActionDefinition, ActionResult
from .system import empty_recycle_bin, execute_power_action


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, ActionDefinition] = {}

    def register(self, definition: ActionDefinition) -> None:
        if definition.action_id in self._actions:
            raise ValueError(f"Действие уже зарегистрировано: {definition.action_id}")
        self._actions[definition.action_id] = definition

    def get(self, action_id: str) -> ActionDefinition:
        try:
            return self._actions[action_id]
        except KeyError as error:
            raise ValueError(f"Неизвестное действие: {action_id}") from error

    def execute(
        self,
        action_id: str,
        arguments: dict[str, object],
    ) -> ActionResult:
        definition = self.validate(action_id, arguments)
        return definition.handler(**arguments)

    def validate(
        self,
        action_id: str,
        arguments: dict[str, object],
    ) -> ActionDefinition:
        definition = self.get(action_id)
        unknown = set(arguments) - set(definition.allowed_arguments)
        if unknown:
            raise ValueError(f"Недопустимые аргументы для {action_id}: {sorted(unknown)}")
        return definition


def create_default_registry(context: ActionContext) -> ActionRegistry:
    registry = ActionRegistry()
    definitions = [
        ActionDefinition(
            "window.close",
            "Закрытие окна",
            partial(close_window, context),
            RiskLevel.DESTRUCTIVE,
        ),
        ActionDefinition(
            "text.type",
            "Ввод текста",
            partial(type_text, context),
            RiskLevel.SENSITIVE,
            frozenset({"text"}),
            frozenset({"text"}),
        ),
        ActionDefinition(
            "web.search",
            "Поиск в интернете",
            partial(search_web, context),
            RiskLevel.VISIBLE,
            frozenset({"query"}),
        ),
        ActionDefinition(
            "web.open",
            "Открытие веб-страницы",
            partial(open_web, context),
            RiskLevel.VISIBLE,
            frozenset({"url"}),
        ),
        ActionDefinition(
            "application.open",
            "Открытие приложения",
            partial(open_application, context),
            RiskLevel.VISIBLE,
            frozenset({"app_id"}),
        ),
        ActionDefinition(
            "project_file.open",
            "Открытие файла проекта",
            partial(open_project_file, context),
            RiskLevel.VISIBLE,
            frozenset({"path"}),
        ),
        ActionDefinition(
            "assistant.say",
            "Локальный ответ",
            lambda **arguments: ActionResult(
                True,
                str(arguments.get("text", "")),
            ),
            RiskLevel.SAFE,
            frozenset({"text"}),
        ),
        ActionDefinition(
            "recycle_bin.empty",
            "Очистка корзины",
            partial(empty_recycle_bin, context),
            RiskLevel.DESTRUCTIVE,
        ),
    ]
    for action_id, label, hotkey_action, risk in (
        ("text.copy", "Копирование текста", "copy", RiskLevel.VISIBLE),
        ("text.select_all", "Выделение всего текста", "select_all", RiskLevel.VISIBLE),
        ("text.paste", "Вставка из буфера обмена", "paste", RiskLevel.SENSITIVE),
        ("text.cut", "Вырезание текста", "cut", RiskLevel.DESTRUCTIVE),
        (
            "text.delete_last_word",
            "Удаление последнего слова",
            "delete_last_word",
            RiskLevel.DESTRUCTIVE,
        ),
        ("text.delete_all", "Удаление всего текста", "delete_all", RiskLevel.DESTRUCTIVE),
        ("message.send", "Отправка сообщения", "send", RiskLevel.DESTRUCTIVE),
        ("text.undo", "Отмена последнего действия", "undo", RiskLevel.VISIBLE),
        ("text.save_as", "Сохранение под новым именем", "save_as", RiskLevel.VISIBLE),
    ):
        definitions.append(
            ActionDefinition(
                action_id,
                label,
                partial(
                    invoke_controller_action,
                    context,
                    method_name="text_hotkey",
                    action=hotkey_action,
                ),
                risk,
            )
        )
    legacy_definitions = (
        ("text.format", "Форматирование текста", "text_hotkey", RiskLevel.VISIBLE, {"action"}),
        ("text.navigate", "Навигация по тексту", "navigate_text", RiskLevel.VISIBLE, {"action"}),
        ("input_language.switch", "Смена языка ввода", "switch_input_language", RiskLevel.VISIBLE, set()),
        ("browser.shortcut", "Команда браузера", "browser_hotkey", RiskLevel.VISIBLE, {"action"}),
        ("image.search", "Поиск изображений", "open_image_search", RiskLevel.VISIBLE, {"query"}),
        ("window.minimize_all", "Сворачивание окон", "minimize_windows", RiskLevel.VISIBLE, set()),
        ("window.minimize", "Сворачивание окна", "minimize_current_window", RiskLevel.VISIBLE, set()),
        ("window.maximize", "Разворачивание окна", "maximize_window", RiskLevel.VISIBLE, set()),
        ("window.switch", "Переключение окна", "switch_window", RiskLevel.VISIBLE, set()),
        ("mouse.click", "Щелчок мышью", "mouse_click", RiskLevel.VISIBLE, {"button"}),
        ("mouse.double_click", "Двойной щелчок мышью", "mouse_double_click", RiskLevel.VISIBLE, set()),
        ("mouse.move", "Перемещение мыши", "move_mouse", RiskLevel.VISIBLE, {"direction"}),
        ("mouse.scroll", "Прокрутка", "scroll", RiskLevel.VISIBLE, {"direction"}),
        ("volume.set", "Изменение громкости", "set_volume_percent", RiskLevel.VISIBLE, {"percent"}),
        ("volume.mute", "Отключение звука", "volume_mute", RiskLevel.VISIBLE, set()),
        ("volume.step", "Изменение громкости", "volume_step", RiskLevel.VISIBLE, {"direction", "presses"}),
        ("brightness.set", "Изменение яркости", "set_brightness_percent", RiskLevel.VISIBLE, {"percent"}),
        ("screen.lock", "Блокировка экрана", "lock_screen", RiskLevel.SYSTEM, set()),
        ("system.cancel_power_timer", "Отмена таймера питания", "cancel_power_timer", RiskLevel.VISIBLE, set()),
    )
    for action_id, label, method_name, risk, arguments in legacy_definitions:
        definitions.append(
            ActionDefinition(
                action_id,
                label,
                partial(invoke_controller_action, context, method_name=method_name),
                risk,
                frozenset(arguments),
            )
        )
    for kind, action_id, label in (
        ("shutdown", "system.shutdown", "Выключение компьютера"),
        ("restart", "system.restart", "Перезагрузка компьютера"),
        ("sleep", "system.sleep", "Спящий режим"),
    ):
        definitions.append(
            ActionDefinition(
                action_id,
                label,
                partial(execute_power_action, context, kind=kind),
                RiskLevel.SYSTEM,
            )
        )
    for definition in definitions:
        registry.register(definition)
    return registry
