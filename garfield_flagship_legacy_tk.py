"""Legacy entry point kept for compatibility.

The maintained Tk/runtime implementation now lives in ``garfield.runtime``.
"""

from garfield_flagship import (
    FlagshipConfig,
    FlagshipGUI,
    FlagshipRuntime,
    choose_ui_mode,
    main,
    run_console,
    save_config,
    setup_logging,
)

__all__ = [
    "FlagshipConfig",
    "FlagshipGUI",
    "FlagshipRuntime",
    "choose_ui_mode",
    "main",
    "run_console",
    "save_config",
    "setup_logging",
]


if __name__ == "__main__":
    raise SystemExit(main())
