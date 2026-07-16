from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def resolve_config_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def clamp_int(
    value: object,
    minimum: int,
    maximum: int,
    field_name: str,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name}: требуется целое число.") from error
    return max(minimum, min(parsed, maximum))


def load_json_config(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.exists():
        return {}, []
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        broken_path = path.with_name(f"{path.stem}.broken-{timestamp}{path.suffix}")
        path.replace(broken_path)
        return (
            {},
            [f"Повреждённый config перемещён в {broken_path.name}; загружены настройки по умолчанию."],
        )
    if not isinstance(payload, dict):
        raise ValueError("Корневой элемент config должен быть JSON-объектом.")
    return payload, []
