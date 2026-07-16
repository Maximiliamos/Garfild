from __future__ import annotations

import json
from pathlib import Path

import pytest

from garfield_best import AppConfig, normalize_llm_provider, validate_llm_api_url
from garfield_config import clamp_int, resolve_config_path
from garfield_flagship import FlagshipConfig


def test_resolve_config_path_uses_config_directory(tmp_path: Path) -> None:
    assert (
        resolve_config_path(
            tmp_path,
            "models/model.bin",
        )
        == (tmp_path / "models" / "model.bin").resolve()
    )


def test_clamp_int_reports_field_and_bounds_value() -> None:
    assert clamp_int("999", 1, 10, "Поле") == 10
    assert clamp_int("-5", 1, 10, "Поле") == 1
    with pytest.raises(ValueError, match="Поле: требуется целое число"):
        clamp_int("not-a-number", 1, 10, "Поле")


@pytest.mark.parametrize(
    "url",
    [
        "http://api.openai.com/v1/chat/completions",
        "https://user:password@api.openai.com/v1/chat/completions",
        "https:///missing-host",
    ],
)
def test_llm_api_url_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_llm_api_url("openai", url, allow_custom=True)


def test_llm_api_url_rejects_custom_host_without_opt_in() -> None:
    with pytest.raises(ValueError, match="стандартный API endpoint"):
        validate_llm_api_url(
            "openai",
            "https://llm.example.com/v1/chat/completions",
            allow_custom=False,
        )


def test_llm_api_url_allows_custom_https_host_with_opt_in() -> None:
    url = "https://llm.example.com/v1/chat/completions"

    assert validate_llm_api_url("openai", url, allow_custom=True) == url


def test_relative_paths_from_json_are_resolved_from_config_location(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "vosk_model_path": "models/vosk",
                "skills_path": "skills.json",
                "piper_model_path": "models/piper/model.onnx",
                "piper_config_path": "models/piper/model.onnx.json",
            }
        ),
        encoding="utf-8",
    )

    config = FlagshipConfig.load(path)

    assert config.vosk_model_path == str((tmp_path / "models" / "vosk").resolve())
    assert config.skills_path == str((tmp_path / "skills.json").resolve())
    assert config.piper_model_path == str((tmp_path / "models" / "piper" / "model.onnx").resolve())


def test_broken_json_is_archived_and_defaults_are_loaded(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")

    config = FlagshipConfig.load(path)

    assert not path.exists()
    backups = list(tmp_path.glob("config.broken-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{broken"
    assert config.assistant_name
    assert config.load_warnings


@pytest.mark.parametrize("config_class", [AppConfig, FlagshipConfig])
def test_invalid_activation_mode_falls_back_to_wake_word(
    config_class,
    tmp_path: Path,
) -> None:
    path = tmp_path / f"{config_class.__name__}.json"
    path.write_text(json.dumps({"activation_mode": "invalid"}), encoding="utf-8")

    assert config_class.load(path).activation_mode == "wake_word"


def test_grok_provider_alias_maps_to_xai() -> None:
    assert normalize_llm_provider("grok") == "xai"
