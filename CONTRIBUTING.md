# Contributing

Требуются Python 3.11–3.13 и `uv`.

```powershell
uv sync --locked --extra dev
uv run python -m compileall .
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pip-audit
```

Правила изменений:

- не выполнять реальные desktop/audio/power-команды в тестах;
- не добавлять секреты, модели и бинарные файлы;
- любое desktop-действие регистрировать в Action Registry;
- для опасных действий задавать risk level и подтверждение;
- изменения форматов config/skills сопровождать миграцией;
- функциональные изменения и массовое форматирование разделять;
- один логический этап — один коммит.
