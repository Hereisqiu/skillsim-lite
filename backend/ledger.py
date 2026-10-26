"""Per-request measurement ledger: one JSON line per model API attempt, written by the model client.

Token counts are copied from the API's `usage` object. A field the API did not report is stored
as null ("unavailable"), never as 0.
"""

from __future__ import annotations

import json
import threading

from . import security
from .config import DATA_DIR

LEDGER_FILE = DATA_DIR / "requests.jsonl"
_lock = threading.Lock()


def record(entry: dict) -> None:
    with _lock, LEDGER_FILE.open("a") as f:
        f.write(json.dumps(security.redact(entry)) + "\n")


def read_all() -> list[dict]:
    if not LEDGER_FILE.is_file():
        return []
    rows = []
    for line in LEDGER_FILE.read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn line shouldn't hide the rest
    return rows
