# Garfield General

Основная пользовательская версия проекта: `garfield_flagship.py`.

`garfield_best.py` содержит ядро ассистента: команды, распознавание речи через Vosk,
озвучку, кэш ответов, историю диалога и подключение к ИИ-провайдерам.

## Возможности

- Современный GUI-dashboard на `customtkinter` с fallback на legacy `tkinter` и консоль.
- Голосовой ввод через Vosk с автопрослушиванием, выбором микрофона, тестом уровня и режимами `continuous` / `wake_word`.
- Озвучка ответов через Piper `ru_RU-irina-medium`, Edge TTS и локальные fallback-голоса Windows.
- Последовательная обработка команд и очередь TTS, чтобы GUI, ответы и озвучка не мешали друг другу.
- Ответы через выбираемый ИИ-провайдер: NVIDIA, OpenAI, Google Gemini, Groq Cloud или xAI Grok.
- Выбор модели в настройках: NVIDIA Kimi K2.5 / Llama 3.1, OpenAI GPT-4.1 Mini / GPT-4o Mini, Gemini 2.5 Flash / Flash Lite / Pro, Groq Llama/GPT-OSS, xAI Grok 4.3 / Grok 4.
- Короткая память диалога, кэш ответов, экспорт истории сессии.
- Desktop-команды: браузер, YouTube, интернет-поиск, окна, вкладки, мышь, текст, громкость и яркость.
- Безопасное подтверждение команд выключения, перезагрузки и сна.
- Диагностика Vosk, Piper, ИИ-провайдера, микрофона, вывода, навыков и состояния прослушивания.

## Быстрый запуск

1. Установите Python 3.10+.
2. Установите зависимости: `pip install -r requirements.txt`.
3. Проверьте путь `vosk_model_path` в `garfield_flagship_config.json`.
4. Запустите `Start_Garfild.bat`.

`Start_Garfild.bat` ищет Python в `.venv`, затем в `C:\Python314`, затем через `py` или `python`, и запускает `garfield_flagship.py`.

## Настройка ИИ

В разделе настроек выберите:

- `llm_provider`: `nvidia`, `openai`, `gemini`, `groq` или `xai`.
- `llm_model`: модель из списка для выбранного провайдера.
- API-ключ нужного провайдера или переменную окружения `NVIDIA_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `XAI_API_KEY`.

Рабочий конфиг хранится в `garfield_flagship_config.json`, шаблон без ключей - в `garfield_flagship_config.json.example`.

## Голосовой режим

По умолчанию включен режим `continuous`, автопрослушивание и автоматический выбор микрофона. Если ассистент слышит лишнее, переключите `activation_mode` на `wake_word` и используйте ключевую фразу `гарфилд`.

Основные команды:

- `помощь`
- `диагностика`
- `повтори`
- `что ты услышал`
- `очисти память`
- `очисти кэш`
- `сохрани диалог`
- `включи прослушивание`
- `выключи прослушивание`
- `включи озвучку`
- `выключи озвучку`
- `найди ...`

## Файлы

- `Start_Garfild.bat` - единый launcher для Windows.
- `garfield_flagship.py` - главный запуск GUI/console runtime.
- `garfield_flagship_gui.pyw` - запуск dashboard с fallback на legacy GUI.
- `garfield_best.py` - внутренний модуль ядра.
- `garfield_dashboard/` - современный dashboard.
- `garfield_flagship_config.json` - рабочий конфиг.
- `garfield_flagship_config.json.example` - шаблон конфига.
- `garfield_skills.json` - локальные навыки.
- `garfield_flagship.log` - лог приложения.
- `garfield_session_history.txt` - экспорт истории сессии.

## Заметки

- Если `pyautogui` недоступен, desktop-команды сообщат об ограничении.
- Если Vosk-модель не найдена, приложение переключится в текстовый режим, если `input_mode` не установлен строго в `voice`.
- Если выбранный ИИ-провайдер недоступен или долго не отвечает, ассистент использует локальный fallback-ответ.
