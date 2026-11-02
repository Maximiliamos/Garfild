"""Git-based fast-forward updates with explicit user approval.

No background install, no force reset, no arbitrary remote, no shell=True.
Only usable from a clean checkout of the official GitHub repository on main.
Release ZIP/EXE installations need a separate signed installer.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path


class UpdateManager:
    EXPECTED_REMOTE = {
        "https://github.com/maximiliamos/garfild",
        "git@github.com:maximiliamos/garfild",
        "ssh://git@github.com/maximiliamos/garfild",
    }

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.pending_sha: str | None = None
        self.pending_at = 0.0

    def _git(self, *args: str) -> str:
        git = shutil.which("git")
        if not git:
            raise RuntimeError("Git не установлен, автоматическое обновление недоступно")
        completed = subprocess.run(
            [git, "-C", str(self.root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=50,
            check=True,
            shell=False,
        )
        return completed.stdout.strip()

    def _preflight(self):
        remote = self._git("remote", "get-url", "origin").strip().lower().removesuffix(".git").rstrip("/")
        if remote not in self.EXPECTED_REMOTE:
            raise RuntimeError("Обновление разрешено только из официального репозитория Garfield")
        if self._git("branch", "--show-current") != "main":
            raise RuntimeError("Для обновления нужна ветка main")
        if self._git("status", "--porcelain"):
            raise RuntimeError("Есть локальные изменения: сначала сохраните их в отдельном коммите или копии")

    def check(self) -> str:
        self.pending_sha = None
        self._preflight()
        self._git("fetch", "--no-tags", "origin", "main")
        remote_sha = self._git("rev-parse", "FETCH_HEAD")
        if not re.fullmatch(r"[0-9a-f]{40}", remote_sha):
            raise RuntimeError("Не удалось проверить хеш удалённого коммита")
        counts = self._git("rev-list", "--left-right", "--count", "HEAD...FETCH_HEAD").split()
        if len(counts) != 2:
            raise RuntimeError("Не удалось сравнить версии")
        ahead, behind = map(int, counts)
        if ahead:
            return "Локальная версия отличается от удалённой. Автоматическое обновление заблокировано."
        if not behind:
            return "Garfield уже обновлён до последнего коммита main."
        self.pending_sha = remote_sha
        self.pending_at = time.monotonic()
        return (
            f"Обнаружено {behind} новых коммитов. Обновление доступно до {remote_sha[:12]}. "
            "Для установки в течение 10 минут введите «подтверди обновление». "
            "После установки перезапустите Garfield."
        )

    def apply(self) -> str:
        if not self.pending_sha or time.monotonic() - self.pending_at > 600:
            self.pending_sha = None
            return "Нет действительного запроса на обновление. Сначала проверьте обновления."
        original_target = self.pending_sha
        self.pending_sha = None
        self._preflight()
        self._git("fetch", "--no-tags", "origin", "main")
        if self._git("rev-parse", "FETCH_HEAD") != original_target:
            return "Удалённая версия изменилась: проверьте обновления заново."
        self._git("merge", "--ff-only", "FETCH_HEAD")
        return "Код обновлён без перезаписи локальных изменений. Полностью закройте и запустите Garfield заново."

    def cancel(self) -> str:
        self.pending_sha = None
        return "Обновление отменено."
