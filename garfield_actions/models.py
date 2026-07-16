from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from garfield_intents import RiskLevel


@dataclass(frozen=True)
class ActionResult:
    success: bool
    message: str
    details: str | None = None


@dataclass(frozen=True)
class ActionDefinition:
    action_id: str
    display_name: str
    handler: Callable[..., ActionResult]
    risk: RiskLevel
    allowed_arguments: frozenset[str] = frozenset()
    sensitive_arguments: frozenset[str] = frozenset()


@dataclass
class ActionContext:
    platform_name: str
    desktop_enabled: bool
    power_enabled: bool
    metadata: dict[str, Any] = field(default_factory=dict)
