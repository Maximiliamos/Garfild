from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from enum import IntEnum
from re import Pattern


class RiskLevel(IntEnum):
    SAFE = 0
    VISIBLE = 1
    SENSITIVE = 2
    DESTRUCTIVE = 3
    SYSTEM = 4


@dataclass(frozen=True)
class Intent:
    intent_id: str
    arguments: dict[str, str] = field(default_factory=dict)
    risk: RiskLevel = RiskLevel.SAFE
    confidence: float = 1.0
    original_text: str = ""


@dataclass(frozen=True)
class IntentPattern:
    intent_id: str
    pattern: Pattern[str]
    risk: RiskLevel = RiskLevel.SAFE
    allow_negation: bool = False


@dataclass(frozen=True)
class ActionRequest:
    action_id: str
    arguments: dict[str, object]
    risk: RiskLevel
    display_name: str
    sensitive_arguments: frozenset[str] = frozenset()


@dataclass
class PendingAction:
    request: ActionRequest
    created_at: float
    confirmation_token: str
    nonce: str = field(default_factory=lambda: secrets.token_hex(4))

    def is_expired(self, timeout_sec: int) -> bool:
        return time.monotonic() - self.created_at > timeout_sec


PUNCTUATION_RE = re.compile(r"[^\w\s%-]", re.UNICODE)
SPACE_RE = re.compile(r"\s+")


def normalize_command_text(text: str) -> str:
    text = text.casefold().replace("ё", "е")
    text = PUNCTUATION_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


NON_ACTION_PREFIXES = (
    "расскажи ",
    "объясни ",
    "что значит ",
    "как работает ",
    "почему ",
)
NEGATED_REQUEST_PREFIXES = (
    "не ",
    "пожалуйста не ",
    "прошу не ",
    "только не ",
    "ни в коем случае не ",
)


def is_non_action_request(raw_text: str) -> bool:
    """Return true when command-looking text is explicitly not an instruction."""
    text = normalize_command_text(raw_text)
    return text.startswith(NEGATED_REQUEST_PREFIXES) or text.startswith(NON_ACTION_PREFIXES)


NEGATION_WORDS = {
    "не",
    "нет",
    "нельзя",
    "ненадо",
    "не надо",
    "не нужно",
    "не делай",
    "не закрывай",
    "не выключай",
    "не удаляй",
}


def is_match_negated(text: str, match: re.Match[str]) -> bool:
    prefix = text[: match.start()].strip()
    if not prefix:
        return False

    previous_fragment = " ".join(prefix.split()[-4:])
    return any(negation in previous_fragment for negation in NEGATION_WORDS)


INTENT_PATTERNS = [
    IntentPattern(
        intent_id="window.close",
        pattern=re.compile(r"^(?:закрой|закрыть)\s+(?:это\s+)?(?:окно|приложение)$"),
        risk=RiskLevel.DESTRUCTIVE,
    ),
    IntentPattern(
        intent_id="system.shutdown",
        pattern=re.compile(r"^(?:выключи|выключить)\s+(?:компьютер|пк)$"),
        risk=RiskLevel.SYSTEM,
    ),
    IntentPattern(
        intent_id="system.restart",
        pattern=re.compile(r"^(?:перезагрузи|перезагрузить)\s+(?:компьютер|пк)$"),
        risk=RiskLevel.SYSTEM,
    ),
    IntentPattern(
        intent_id="system.sleep",
        pattern=re.compile(
            r"^(?:переведи|отправь)\s+(?:компьютер|пк)\s+в\s+"
            r"(?:сон|спящий режим)$"
        ),
        risk=RiskLevel.SYSTEM,
    ),
    IntentPattern(
        intent_id="recycle_bin.empty",
        pattern=re.compile(r"^(?:очисти|очистить)\s+корзину$"),
        risk=RiskLevel.DESTRUCTIVE,
    ),
    IntentPattern(
        intent_id="text.type",
        pattern=re.compile(r"^(?:напечатай|введи(?:\s+текст)?|набери(?:\s+текст)?)\s+(?P<text>.+)$"),
        risk=RiskLevel.SENSITIVE,
    ),
    IntentPattern(
        intent_id="web.search",
        pattern=re.compile(r"^(?:найди|поищи|поиск)\s+(?P<query>.+)$"),
        risk=RiskLevel.VISIBLE,
    ),
]


CONFIRMATION_TOKENS = {
    "window.close": "закрытие окна",
    "recycle_bin.empty": "очистку корзины",
    "system.shutdown": "выключение компьютера",
    "system.restart": "перезагрузку компьютера",
    "system.sleep": "переход компьютера в спящий режим",
    "text.cut": "вырезание текста",
    "text.delete_last_word": "удаление последнего слова",
    "text.delete_all": "удаление всего текста",
    "message.send": "отправку сообщения",
}


def requires_confirmation(request: ActionRequest) -> bool:
    return request.risk >= RiskLevel.DESTRUCTIVE


def confirmation_token(action_id: str) -> str:
    return CONFIRMATION_TOKENS.get(action_id, action_id)


def is_confirmation(
    text: str,
    pending: PendingAction,
    confirm_phrases: list[str],
) -> bool:
    normalized = normalize_command_text(text)
    normalized_phrases = {normalize_command_text(phrase) for phrase in confirm_phrases}
    if pending.request.risk >= RiskLevel.DESTRUCTIVE:
        full_phrases = {f"{phrase} {pending.confirmation_token}" for phrase in normalized_phrases}
        return normalized in full_phrases
    return normalized in normalized_phrases


def is_cancellation(text: str, cancel_phrases: list[str]) -> bool:
    normalized = normalize_command_text(text)
    return normalized in {normalize_command_text(phrase) for phrase in cancel_phrases}


class IntentRouter:
    def __init__(self, patterns: list[IntentPattern] | None = None) -> None:
        self.patterns = patterns or INTENT_PATTERNS

    def route(self, raw_text: str) -> Intent | None:
        text = normalize_command_text(raw_text)

        for definition in self.patterns:
            match = definition.pattern.fullmatch(text)
            if match is None:
                continue
            if not definition.allow_negation and is_match_negated(text, match):
                return None

            arguments = {key: value.strip() for key, value in match.groupdict().items() if value is not None}
            return Intent(
                intent_id=definition.intent_id,
                arguments=arguments,
                risk=definition.risk,
                original_text=raw_text,
            )

        return None
