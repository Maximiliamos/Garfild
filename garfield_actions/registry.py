from __future__ import annotations

from functools import partial

from garfield_intents import RiskLevel

from .desktop import (
    close_window,
    open_application,
    open_web,
    search_web,
    type_text,
)
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
        definition = self.get(action_id)
        unknown = set(arguments) - set(definition.allowed_arguments)
        if unknown:
            raise ValueError(f"Недопустимые аргументы для {action_id}: {sorted(unknown)}")
        return definition.handler(**arguments)


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
            "recycle_bin.empty",
            "Очистка корзины",
            partial(empty_recycle_bin, context),
            RiskLevel.DESTRUCTIVE,
        ),
    ]
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
