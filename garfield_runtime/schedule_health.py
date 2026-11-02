"""Conservative interpretation of claimed scheduled runs.

A dead parent process is not proof that its child activity or external side
effects are finished. This helper NEVER changes status or authorizes retry.
"""
from __future__ import annotations


def process_identity(*, pid: int | None, created: float | None) -> str:
    if not pid or created is None:
        return "unknown"
    try:
        import psutil
    except ImportError:
        return "unknown"
    try:
        process = psutil.Process(pid)
        if abs(process.create_time() - float(created)) > 2.0:
            return "owner_not_running"
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return "owner_not_running"
        return "owner_alive"
    except psutil.NoSuchProcess:
        return "owner_not_running"
    except (psutil.AccessDenied, OSError, ValueError):
        return "unknown"


def describe_claim(row: dict, *, current_session: str = "") -> str:
    if row.get("status") != "claimed":
        return "completed"
    if not row.get("needs_review"):
        return "recent_heartbeat"
    if row.get("owner_session") and row["owner_session"] == current_session:
        return "own_runtime_stale"
    return process_identity(pid=row.get("owner_pid"), created=row.get("owner_created"))
