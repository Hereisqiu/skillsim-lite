"""App-wide daily spend ledger, saved to data/spend.json."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from .config import DATA_DIR

SPEND_FILE = DATA_DIR / "spend.json"
_lock = threading.Lock()


def _day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load() -> dict:
    try:
        return json.loads(SPEND_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def today() -> dict:
    return _load().get(_day(), {"tokens": 0, "cost_usd": 0.0, "calls": 0})


def record(tokens: int, cost_usd: float) -> None:
    with _lock:
        ledger = _load()
        day = ledger.setdefault(_day(), {"tokens": 0, "cost_usd": 0.0, "calls": 0})
        day["tokens"] += tokens
        day["cost_usd"] = round(day["cost_usd"] + cost_usd, 6)
        day["calls"] += 1
        SPEND_FILE.write_text(json.dumps(ledger, indent=2))
