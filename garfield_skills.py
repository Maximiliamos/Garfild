from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from garfield_actions import ActionRegistry
from garfield_io import atomic_write_text

ALLOWED_SKILL_ACTIONS = {
    "assistant.say",
    "web.open",
    "web.search",
    "application.open",
    "project_file.open",
}


@dataclass(frozen=True)
class LocalSkill:
    skill_id: str
    phrases: list[str]
    action_id: str
    arguments: dict[str, str] = field(default_factory=dict)
    response: str = ""


@dataclass(frozen=True)
class SkillMatch:
    skill: LocalSkill
    variables: dict[str, str]


def normalize_skill_text(text: str) -> str:
    return " ".join(text.casefold().strip().split())


def resolve_beneath(root: Path, raw_path: str) -> Path:
    if Path(raw_path).is_absolute():
        raise ValueError("Абсолютные пути в навыках запрещены.")
    root = root.resolve()
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("Путь навыка выходит за пределы разрешённой папки.") from error
    return candidate


def validate_public_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"https", "http"}:
        raise ValueError("Разрешены только HTTP/HTTPS URL.")
    if not parsed.hostname:
        raise ValueError("URL не содержит имя узла.")
    if parsed.username or parsed.password:
        raise ValueError("URL со встроенным логином или паролем запрещён.")
    return raw_url


def migrate_skill_v1(raw: dict) -> dict | None:
    action = str(raw.get("action", "")).strip().lower()
    if raw.get("use_shell"):
        return None
    common = {
        "id": raw.get("id", ""),
        "phrases": raw.get("phrases", []),
        "response": raw.get("response", ""),
    }
    if action == "say":
        return {**common, "action_id": "assistant.say", "arguments": {}}
    if action == "run" and str(raw.get("target", "")).lower() == "calc.exe":
        return {
            **common,
            "action_id": "application.open",
            "arguments": {"app_id": "calculator"},
        }
    if action == "open_url":
        return {
            **common,
            "action_id": "web.open",
            "arguments": {"url": raw.get("target", "")},
        }
    if action == "search_web":
        return {
            **common,
            "action_id": "web.search",
            "arguments": {"query": "{query}"},
        }
    if action == "open_path":
        return {
            **common,
            "action_id": "project_file.open",
            "arguments": {"path": raw.get("target", "")},
        }
    return None


class SkillRegistry:
    def __init__(
        self,
        path: Path,
        actions: ActionRegistry,
        *,
        project_root: Path,
    ) -> None:
        self.path = path
        self.actions = actions
        self.project_root = project_root.resolve()
        self.skills: list[LocalSkill] = []
        self.load_error: str | None = None
        self.warnings: list[str] = []
        self.reload()

    def reload(self) -> tuple[int, str | None]:
        self.skills = []
        self.load_error = None
        self.warnings = []
        if not self.path.exists():
            return 0, None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            payload = self._migrate_payload(payload)
            items = payload.get("skills", [])
            if not isinstance(items, list):
                raise ValueError("Поле skills должно быть списком.")
            for index, raw_skill in enumerate(items, start=1):
                try:
                    self.skills.append(self._parse_skill(raw_skill, index))
                except (TypeError, ValueError) as error:
                    self.warnings.append(f"Навык {index} отклонён: {error}")
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            self.load_error = str(error)
        return len(self.skills), self.load_error

    def _migrate_payload(self, payload: object) -> dict:
        if isinstance(payload, dict) and payload.get("version") == 2:
            return payload
        items = payload.get("skills", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("Корневой элемент skills должен быть списком.")
        migrated = [
            migrated for raw in items if isinstance(raw, dict) if (migrated := migrate_skill_v1(raw)) is not None
        ]
        rejected = len(items) - len(migrated)
        backup = self.path.with_name(f"{self.path.stem}.v1-backup-{datetime.now():%Y%m%d-%H%M%S}{self.path.suffix}")
        shutil.copy2(self.path, backup)
        new_payload = {"version": 2, "skills": migrated}
        atomic_write_text(
            self.path,
            json.dumps(new_payload, ensure_ascii=False, indent=2) + "\n",
        )
        if rejected:
            self.warnings.append(f"Отклонено небезопасных навыков при миграции: {rejected}.")
        return new_payload

    def _parse_skill(self, raw: object, index: int) -> LocalSkill:
        if not isinstance(raw, dict):
            raise ValueError("описание навыка должно быть объектом")
        action_id = str(raw.get("action_id", "")).strip()
        if action_id not in ALLOWED_SKILL_ACTIONS:
            raise ValueError(f"действие не разрешено: {action_id or '<пусто>'}")
        phrases = raw.get("phrases", [])
        if isinstance(phrases, str):
            phrases = [phrases]
        if not isinstance(phrases, list):
            raise ValueError("phrases должно быть списком")
        normalized_phrases = [
            normalize_skill_text(str(phrase)) for phrase in phrases if normalize_skill_text(str(phrase))
        ]
        if not normalized_phrases:
            raise ValueError("не заданы фразы")
        arguments = raw.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("arguments должно быть объектом")
        string_arguments = {str(key): str(value) for key, value in arguments.items()}
        self._validate_arguments(action_id, string_arguments)
        return LocalSkill(
            skill_id=str(raw.get("id") or f"skill_{index}"),
            phrases=normalized_phrases,
            action_id=action_id,
            arguments=string_arguments,
            response=str(raw.get("response", "") or ""),
        )

    def _validate_arguments(
        self,
        action_id: str,
        arguments: dict[str, str],
    ) -> None:
        definition = self.actions.get(action_id)
        unknown = set(arguments) - set(definition.allowed_arguments)
        if unknown:
            raise ValueError(f"недопустимые аргументы: {sorted(unknown)}")
        if action_id == "web.open":
            validate_public_url(arguments.get("url", ""))
        if action_id == "application.open":
            app_id = arguments.get("app_id", "")
            if app_id not in {"calculator", "notepad"}:
                raise ValueError(f"неизвестное приложение: {app_id}")
        if action_id == "project_file.open":
            resolve_beneath(self.project_root, arguments.get("path", ""))

    def count(self) -> int:
        return len(self.skills)

    def describe(self) -> str:
        if self.load_error:
            return f"Ошибка загрузки навыков: {self.load_error}"
        if not self.skills:
            return "Навыки не загружены."
        labels = ", ".join(skill.skill_id for skill in self.skills[:8])
        suffix = "" if len(self.skills) <= 8 else f" и ещё {len(self.skills) - 8}"
        warning = f" Предупреждений: {len(self.warnings)}." if self.warnings else ""
        return f"Навыки: {labels}{suffix}.{warning}"

    def match(self, text: str) -> SkillMatch | None:
        normalized = normalize_skill_text(text)
        for skill in self.skills:
            for phrase in skill.phrases:
                if "{query}" in phrase:
                    prefix, _, suffix = phrase.partition("{query}")
                    if prefix and not normalized.startswith(prefix):
                        continue
                    if suffix and not normalized.endswith(suffix):
                        continue
                    query = normalized[len(prefix) :]
                    if suffix:
                        query = query[: -len(suffix)]
                    query = query.strip(" ,.!?-")
                    if query:
                        return SkillMatch(
                            skill,
                            {"query": query, "query_url": quote_plus(query)},
                        )
                elif normalized == phrase:
                    return SkillMatch(
                        skill,
                        {"query": "", "query_url": ""},
                    )
        return None

    def execute(self, match: SkillMatch) -> str:
        skill = match.skill
        variables = {**match.variables}
        arguments = {key: value.format(**variables) for key, value in skill.arguments.items()}
        if skill.action_id == "assistant.say":
            return skill.response.format(**variables) or "Навык выполнен."
        result = self.actions.execute(skill.action_id, arguments)
        if skill.response:
            return skill.response.format(**variables)
        return result.message
