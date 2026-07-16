from __future__ import annotations

import json
from pathlib import Path

from garfield_best import SkillRegistry


def test_skill_registry_loads_and_matches_safe_say_skill(tmp_path: Path) -> None:
    skills_path = tmp_path / "skills.json"
    skills_path.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "id": "greeting",
                        "phrases": ["скажи привет"],
                        "action": "say",
                        "response": "Привет!",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    registry = SkillRegistry(skills_path)
    match = registry.match("  СКАЖИ   ПРИВЕТ ")

    assert registry.count() == 1
    assert registry.load_error is None
    assert match is not None
    assert registry.execute(match) == "Привет!"


def test_skill_registry_reports_invalid_json_without_raising(tmp_path: Path) -> None:
    skills_path = tmp_path / "skills.json"
    skills_path.write_text("{broken", encoding="utf-8")

    registry = SkillRegistry(skills_path)

    assert registry.count() == 0
    assert registry.load_error
