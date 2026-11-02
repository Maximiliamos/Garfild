"""Explicit, opt-in screen inspection by an Ollama vision model on loopback.

Never send desktop pixels to a cloud provider, never save screenshots to disk.
The screen can contain credentials, personal messages and other sensitive data:
users must explicitly request this operation. Models are installed separately.
"""
from __future__ import annotations

import base64
import io
from urllib.parse import urlsplit



def require_loopback(url: str) -> None:
    target = urlsplit(url)
    if target.scheme != "http" or target.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Визуальный анализ разрешён только через локальный Ollama на loopback")
    if target.username or target.password or target.fragment:
        raise ValueError("Некорректный адрес локальной модели")


def analyze_screen(
    prompt: str = "Опиши открытые окна и видимые элементы интерфейса по-русски.",
    *,
    model: str = "llava:7b",
    url: str = "http://127.0.0.1:11434/api/generate",
    image_bytes: bytes | None = None,
    session: object | None = None,
) -> str:
    if not 1 <= len(prompt) <= 1000:
        raise ValueError("Описание задачи не должно превышать 1000 символов")
    if not model or len(model) > 128:
        raise ValueError("Необходимо выбрать vision-модель")
    require_loopback(url)
    if image_bytes is None:
        try:
            import pyautogui
        except ImportError as error:
            raise RuntimeError("Для захвата экрана требуется pyautogui") from error
        screenshot = pyautogui.screenshot()
        screenshot.thumbnail((1280, 900))
        stream = io.BytesIO()
        screenshot.convert("RGB").save(stream, format="JPEG", quality=75)
        image_bytes = stream.getvalue()
    if not image_bytes or len(image_bytes) > 3_500_000:
        raise ValueError("Изображение экрана слишком большое или пустое")
    if session is None:
        import requests
        session = requests
    client = session
    response = client.post(
        url, json={
            "model": model, "prompt": prompt, "images": [base64.b64encode(image_bytes).decode("ascii")],
            "stream": False, "options": {"num_predict": 350},
        },
        timeout=(5, 85),
    )
    response.raise_for_status()
    data = response.json()
    answer = data.get("response") if isinstance(data, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Ollama не вернул описание изображения; проверьте выбранную vision-модель")
    return answer.strip()[:6000]
