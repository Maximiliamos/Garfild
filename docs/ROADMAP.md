# Garfield development roadmap

## Implemented on this branch
- Add a constrained agent JSON planner with user approval and 6-step limit; results are recorded in SQLite.
- Allowlist of local tools including workspace files, notes, app launch, browser and web search.
- Add a dashboard tab for agent plans, workflow JSON validation/editor and local notes.
- Add opt-in SQLite conversation persistence and safe read-only daily scheduling.
- Add optional localhost-only Ollama API provider (requires a separately installed Ollama server and model).
- Fix exact exit-command matching (avoids "покажи" triggering "пока").
- Fix Grok provider alias to xAI.
- Context-aware, model-specific response cache with a 5-minute TTL; do not cache API-failure fallbacks.
- Isolate command-handler failures so a single bad command does not kill the worker.
- Require explicit user confirmation before executing local run/python/hotkey skills.
- Disallow shell=True in configured run skills.
- Limit visible dashboard chat rows and history rendering.
- Add static regression tests and GitHub CI.

## Not yet implemented or verified
- Windows Credential Manager / DPAPI secret storage and migration.
- Automated Ollama model download and llama.cpp provider (basic local Ollama HTTP integration is implemented).
- Encrypted personal memory, automatic retrieval of relevant notes and cross-device sync (SQLite notes + opt-in local conversation history implemented).
- Trigger-based workflows, drag-and-drop visual editor and rollback (JSON workflows + daily read-only scheduler + GUI editor implemented).
- Faster-whisper integration and dedicated wake word model.
- Signed Windows installer and automatic updater.
- Full modularization of core/GUI and dependency isolation.
- Automated hardware-in-the-loop testing of Vosk/Piper/audio and desktop automation.
- Actual API compatibility with the model IDs supplied by providers.

## Security notes
Skills run with the privileges of the user running Garfield. Do not load untrusted skills files or
untrusted Python scripts. Confirmation helps prevent accidental execution but is not a sandbox.
The config currently saves API keys in a local plaintext JSON; use environment variables and
restrict access until DPAPI integration is finished.

## Test on a Windows PC
1. Create a Python 3.11 virtual environment and install requirements.
2. Run `python -m unittest discover -s tests -v`.
3. Check `покажи список команд` does not exit and `выход` does.
4. Verify a run/python/hotkey skill asks for confirmation and cancels on "нет".
5. Test microphone changes during active Vosk recognition.
6. Check TTS interruption, log export and graceful exit.
