# Skills v2

Файл имеет корневой объект:

```json
{
  "version": 2,
  "skills": [
    {
      "id": "docs",
      "phrases": ["открой документацию"],
      "action_id": "project_file.open",
      "arguments": {"path": "README.md"}
    }
  ]
}
```

Разрешённые действия:

- `assistant.say`
- `web.open`
- `web.search`
- `application.open`
- `project_file.open`

Запрещены `run`, `python`, `powershell`, `cmd`, `shell`, `hotkey` и `script`.
URL должен быть HTTP/HTTPS без встроенных credentials. Путь к файлу должен быть
относительным и оставаться внутри корня проекта. Пользовательский `{query}` может
изменять только разрешённый аргумент, но не `action_id`.

При загрузке v1 создаётся backup. Известные безопасные команды мигрируют,
небезопасные навыки отклоняются с предупреждением.
