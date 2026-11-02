"""Manual Windows diagnostics: no cloud access, never uploads audio.

Run: python tools/diagnose_windows.py
     python tools/diagnose_windows.py --mic
The --mic option records a short audio sample only in memory and reports RMS.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from pathlib import Path


def report(test_mic: bool = False) -> dict:
    result = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "modules": {},
        "audio": {},
        "local_paths": {},
    }
    for name in ("vosk", "faster_whisper", "sounddevice", "piper", "pyautogui", "customtkinter", "pywinauto", "playwright"):
        try:
            result["modules"][name] = importlib.util.find_spec(name) is not None
        except Exception:
            result["modules"][name] = False
    root = Path(__file__).resolve().parents[1]
    for name in ("garfield_flagship_config.json", "garfield_workflows.json", "models"):
        result["local_paths"][name] = (root / name).exists()
    if result["modules"]["sounddevice"]:
        import sounddevice as sd
        try:
            devices = sd.query_devices()
            result["audio"]["inputs"] = [
                {"index": index, "name": str(device["name"])[:90]}
                for index, device in enumerate(devices)
                if device["max_input_channels"] > 0
            ]
            result["audio"]["outputs"] = [
                {"index": index, "name": str(device["name"])[:90]}
                for index, device in enumerate(devices)
                if device["max_output_channels"] > 0
            ]
        except Exception as error:
            result["audio"]["error"] = str(error)
        if test_mic:
            try:
                import numpy as np
                recorded = sd.rec(16000 * 2, samplerate=16000, channels=1, dtype="float32")
                sd.wait()
                result["audio"]["mic_rms"] = round(float(np.sqrt(np.mean(recorded * recorded))), 5)
                result["audio"]["mic_has_signal"] = result["audio"]["mic_rms"] > 0.001
            except Exception as error:
                result["audio"]["mic_test_error"] = str(error)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Garfield local hardware diagnostics")
    parser.add_argument("--mic", action="store_true", help="Record 2 seconds in memory to test microphone")
    args = parser.parse_args()
    print(json.dumps(report(args.mic), ensure_ascii=False, indent=2))
