from __future__ import annotations

import json
from pathlib import Path

import pytest

from garfield_actions import ActionContext, create_default_registry
from garfield_skills import SkillRegistry, resolve_beneath


def make_registry(path: Path, project_root: Path) -> SkillRegistry:
    actions = create_default_registry(
        ActionContext(
            platform_name="Windows",
            desktop_enabled=False,
            power_enabled=False,
            metadata={"project_root": project_root},
        )
    )
    return SkillRegistry(path, actions, project_root=project_root)


def test_skill_registry_loads_and_matches_safe_say_skill(tmp_path: Path) -> None:
    skills_path = tmp_path / "skills.json"
    skills_path.write_text(
        json.dumps(
            {
                "version": 2,
                "skills": [
                    {
                        "id": "greeting",
                        "phrases": ["скажи привет"],
                        "action_id": "assistant.say",
                        "arguments": {},
                        "response": "Привет!",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    registry = make_registry(skills_path, tmp_path)
    match = registry.match("  СКАЖИ   ПРИВЕТ ")

    assert registry.count() == 1
    assert registry.load_error is None
    assert match is not None
    assert registry.execute(match) == "Привет!"


def test_skill_registry_reports_invalid_json_without_raising(tmp_path: Path) -> None:
    skills_path = tmp_path / "skills.json"
    skills_path.write_text("{broken", encoding="utf-8")

    registry = make_registry(skills_path, tmp_path)

    assert registry.count() == 0
    assert registry.load_error


@pytest.mark.parametrize(
    ("action", "target"),
    [
        ("python", "script.py"),
        ("hotkey", ""),
    ],
)
def test_unsafe_v1_skill_is_rejected(
    tmp_path: Path,
    action: str,
    target: str,
) -> None:
    skills_path = tmp_path / "skills.json"
    skills_path.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "id": "unsafe",
                        "phrases": ["опасный навык"],
                        "action": action,
                        "target": target,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    registry = make_registry(skills_path, tmp_path)

    assert registry.count() == 0
    assert list(tmp_path.glob("skills.v1-backup-*.json"))


def test_known_v1_run_skill_is_migrated_to_safe_application(tmp_path: Path) -> None:
    skills_path = tmp_path / "skills.json"
    skills_path.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "id": "calculator",
                        "phrases": ["открой калькулятор"],
                        "action": "run",
                        "target": "calc.exe",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    registry = make_registry(skills_path, tmp_path)

    assert registry.count() == 1
    assert registry.skills[0].action_id == "application.open"
    assert registry.skills[0].arguments == {"app_id": "calculator"}
    assert list(tmp_path.glob("skills.v1-backup-*.json"))


def test_shell_skill_is_rejected(tmp_path: Path) -> None:
    skills_path = tmp_path / "skills.json"
    skills_path.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "id": "shell",
                        "phrases": ["опасный навык"],
                        "action": "run",
                        "target": "calc.exe",
                        "use_shell": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert make_registry(skills_path, tmp_path).count() == 0


def test_absolute_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Абсолютные пути"):
        resolve_beneath(tmp_path, str((tmp_path / "secret.txt").resolve()))


def test_parent_directory_traversal_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="за пределы"):
        resolve_beneath(tmp_path / "skills", "../../secret.txt")


def test_unknown_action_is_rejected(tmp_path: Path) -> None:
    skills_path = tmp_path / "skills.json"
    skills_path.write_text(
        json.dumps(
            {
                "version": 2,
                "skills": [
                    {
                        "id": "unknown",
                        "phrases": ["неизвестный навык"],
                        "action_id": "system.shutdown",
                        "arguments": {},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    registry = make_registry(skills_path, tmp_path)

    assert registry.count() == 0
    assert registry.warnings


def test_user_query_cannot_change_action_id(tmp_path: Path) -> None:
    skills_path = tmp_path / "skills.json"
    skills_path.write_text(
        json.dumps(
            {
                "version": 2,
                "skills": [
                    {
                        "id": "search",
                        "phrases": ["найди {query}"],
                        "action_id": "web.search",
                        "arguments": {"query": "{query}"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    registry = make_registry(skills_path, tmp_path)

    match = registry.match("найди system.shutdown")

    assert match is not None
    assert match.skill.action_id == "web.search"
    assert match.variables["query"] == "system.shutdown"
