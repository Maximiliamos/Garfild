from __future__ import annotations

import json
from pathlib import Path


def test_core_imports() -> None:
    import garfield_best
    import garfield_flagship

    assert garfield_best is not None
    assert garfield_flagship is not None


def test_packaged_api_preserves_legacy_import_identity() -> None:
    import garfield_best
    import garfield_flagship
    from garfield.audio import Speaker, VoiceRecognizer
    from garfield.config import AppConfig, FlagshipConfig
    from garfield.conversation import AssistantCore
    from garfield.runtime import FlagshipRuntime

    assert AppConfig is garfield_best.AppConfig
    assert AssistantCore is garfield_best.AssistantCore
    assert VoiceRecognizer is garfield_best.VoiceRecognizer
    assert Speaker is garfield_best.Speaker
    assert FlagshipConfig is garfield_flagship.FlagshipConfig
    assert FlagshipRuntime is garfield_flagship.FlagshipRuntime


def test_config_load_ignores_unknown_fields(tmp_path: Path) -> None:
    from garfield_flagship import FlagshipConfig

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "assistant_name": "Тестовый Гарфилд",
                "input_mode": "keyboard",
                "unknown_future_field": "ignored",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = FlagshipConfig.load(config_path)

    assert config.assistant_name == "Тестовый Гарфилд"
    assert config.input_mode == "keyboard"
    assert not hasattr(config, "unknown_future_field")
