"""Windows DPAPI protection for persisted API keys.

Never substitute reversible home-grown encryption. Outside Windows, configure
API credentials via environment variables; nonempty plaintext keys cannot
be persisted by this module.
"""
from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes
from typing import Any

KEYS = ("nvidia_api_key", "openai_api_key", "gemini_api_key", "groq_api_key", "xai_api_key")
PREFIX = "dpapi:"


class _Blob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _crypt(payload: bytes, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("DPAPI доступен только на Windows. Используйте переменные окружения API_KEY")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    raw = ctypes.create_string_buffer(payload)
    src = _Blob(len(payload), ctypes.cast(raw, ctypes.POINTER(ctypes.c_ubyte)))
    dest = _Blob()
    flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
    if decrypt:
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(src), None, None, None, None, flags, ctypes.byref(dest)
        )
    else:
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_Blob), ctypes.c_wchar_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        ok = crypt32.CryptProtectData(
            ctypes.byref(src), "Garfield API credential", None, None, None, flags,
            ctypes.byref(dest),
        )
    if not ok:
        raise OSError(ctypes.get_last_error(), "Не удалось расшифровать или защитить DPAPI-ключ")
    try:
        return ctypes.string_at(dest.pbData, dest.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(dest.pbData, ctypes.c_void_p))


def protect(value: str) -> str:
    if not value or value.startswith(PREFIX):
        return value
    return PREFIX + base64.b64encode(_crypt(value.encode("utf-8"), False)).decode("ascii")


def reveal(value: str) -> str:
    if not value or not value.startswith(PREFIX):
        return value
    try:
        return _crypt(base64.b64decode(value[len(PREFIX):], validate=True), True).decode("utf-8")
    except Exception as error:
        raise RuntimeError("Зашифрованный API-ключ нельзя прочитать текущим пользователем Windows") from error


def for_disk(config: dict[str, Any]) -> dict[str, Any]:
    data = config.copy()
    for key in KEYS:
        if isinstance(data.get(key), str):
            data[key] = protect(data[key])
    return data


def from_disk(config: dict[str, Any]) -> dict[str, Any]:
    data = config.copy()
    for key in KEYS:
        if isinstance(data.get(key), str):
            data[key] = reveal(data[key])
    return data
