"""Pure workflow step operations used by the visual editor."""
from __future__ import annotations


def move_step(steps: list[dict], old_index: int, new_index: int) -> list[dict]:
    if not 0 <= old_index < len(steps) or not 0 <= new_index < len(steps):
        raise IndexError("Номер шага выходит за пределы сценария")
    updated = [dict(step) for step in steps]
    updated.insert(new_index, updated.pop(old_index))
    return updated


def replace_step(steps: list[dict], index: int, step: dict) -> list[dict]:
    if not 0 <= index < len(steps):
        raise IndexError("Шаг не найден")
    updated = [dict(old) for old in steps]
    updated[index] = {"tool": step["tool"], "args": dict(step["args"])}
    return updated


def delete_step(steps: list[dict], index: int) -> list[dict]:
    if not 0 <= index < len(steps):
        raise IndexError("Шаг не найден")
    return [dict(s) for i, s in enumerate(steps) if i != index]
