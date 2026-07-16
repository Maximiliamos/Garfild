# Garfild Assistant

Локальный Windows desktop-помощник с Vosk, TTS, безопасным Action Registry и
подключаемыми LLM-провайдерами. Текущий релиз: `v0.2.0-security-preview`.

## Установка

Требуется Python 3.11–3.13 и [uv](https://docs.astral.sh/uv/).

```powershell
uv sync --locked --extra dev
Copy-Item garfield_flagship_config.json.example garfield_flagship_config.json
uv run python garfield_flagship.py
```

Модели Vosk/Piper не входят в lock-файл. Разместите их по путям из example
config или укажите собственные пути.

## Безопасность

- LLM отвечает только текстом и не выполняет desktop-команды.
- Локальные действия проходят через типизированный Action Registry.
- Опасные действия требуют подтверждения.
- Skills v2 разрешает только зарегистрированные безопасные `action_id`.
- API-ключи хранятся в Windows Credential Manager через `keyring` или env.
- Постоянная история выключена по умолчанию.
- Custom LLM endpoint требует явного включения и HTTPS.

Подробности: [SECURITY.md](SECURITY.md), [PRIVACY.md](PRIVACY.md) и
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

## API-ключи

Ключ можно сохранить на странице настроек либо задать переменной окружения:

- `NVIDIA_API_KEY`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `GROQ_API_KEY`
- `XAI_API_KEY`

Env имеет приоритет над keyring. Секреты не сериализуются в config JSON.

## Голосовые режимы

- `wake_word`: локальное прослушивание для ключевой фразы, затем команды.
- `continuous`: микрофон постоянно слушается, пока режим включён.

Звук обрабатывается локально Vosk и не отправляется LLM.

## Структура

- `garfield/` — пакет config/privacy/conversation/intents/actions/skills/providers/audio/runtime.
- `garfield_best.py`, `garfield_flagship.py` — compatibility entry points.
- `garfield_dashboard/` — CustomTkinter GUI.
- `garfield_actions/` — реализация Action Registry.
- `tests/` — unit и regression tests без реальных desktop/audio действий.

## Проверки

```powershell
uv run python -m compileall .
uv run pytest -q --cov
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pip-audit
```

См. [CONTRIBUTING.md](CONTRIBUTING.md) и [CHANGELOG.md](CHANGELOG.md).
