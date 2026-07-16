# Changelog

## 0.2.0-security-preview — 2026-07-16

- Добавлен intent router с отрицаниями и общий risk/confirmation engine.
- Desktop-команды и навыки переведены на Action Registry; skills v2 закрывает shell/python.
- API-ключи перенесены в системный keyring.
- Защищены логи, история и экспорт; постоянная история выключена по умолчанию.
- Исправлены LLM parsing, contextual cache с TTL и ограничения размера ответа.
- Ограничены runtime-очереди, исправлены shutdown и lifecycle микрофона.
- Добавлена валидация config, путей и LLM endpoint.
- Ядро и runtime перенесены в пакет `garfield` с compatibility-адаптерами.

Это preview-релиз, не 1.0.
