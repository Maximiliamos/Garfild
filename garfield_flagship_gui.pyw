import logging
from pathlib import Path

import garfield_flagship as app


def main() -> int:
    app.setup_logging()
    config = app.FlagshipConfig.load(Path(app.CONFIG_PATH))
    runtime = app.FlagshipRuntime(config)
    try:
        from garfield_dashboard.app_shell import run_dashboard

        run_dashboard(
            runtime,
            save_config=app.save_config,
            base_dir=app.BASE_DIR,
            config_path=app.CONFIG_PATH,
            log_path=app.LOG_PATH,
            session_log_path=app.SESSION_LOG_PATH,
        )
    except Exception as error:
        logging.exception("Modern dashboard недоступен, запускаю legacy GUI: %s", error)
        gui = app.FlagshipGUI(runtime)
        gui.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
