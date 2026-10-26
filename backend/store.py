"""Session storage: data/sessions.json, cached in memory and reloaded when another process
(e.g. the benchmark script) changes the file, so concurrent writers merge instead of overwriting."""

from __future__ import annotations

import json
import threading

from .config import DATA_DIR

SESSIONS_FILE = DATA_DIR / "sessions.json"
_lock = threading.RLock()
_sessions: dict[str, dict] = {}
_mtime: float | None = None


def _read_file() -> dict:
    try:
        data = json.loads(SESSIONS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}  # a missing or corrupt history file shouldn't stop the app
    for s in data.values():  # sessions saved by older versions
        s.setdefault("trace", [])
        s.setdefault("last_activity", s["started_at"])
        s.setdefault("engine", "mock")
        s.setdefault("model", None)
    return data


def _refresh() -> None:
    global _mtime
    try:
        mtime = SESSIONS_FILE.stat().st_mtime
    except FileNotFoundError:
        mtime = None
    if mtime != _mtime:
        _sessions.clear()
        _sessions.update(_read_file())
        _mtime = mtime


def _save() -> None:
    global _mtime
    SESSIONS_FILE.write_text(json.dumps(_sessions, indent=2))
    _mtime = SESSIONS_FILE.stat().st_mtime


def get(session_id: str) -> dict | None:
    with _lock:
        _refresh()
        return _sessions.get(session_id)


def put(session: dict) -> None:
    with _lock:
        _refresh()
        _sessions[session["id"]] = session
        _save()


def all_sessions() -> list[dict]:
    with _lock:
        _refresh()
        return sorted(_sessions.values(), key=lambda s: s["started_at"], reverse=True)


def delete_where(predicate) -> int:
    with _lock:
        _refresh()
        doomed = [sid for sid, s in _sessions.items() if predicate(s)]
        for sid in doomed:
            del _sessions[sid]
        _save()
        return len(doomed)


def clear() -> None:
    with _lock:
        _sessions.clear()
        _save()
