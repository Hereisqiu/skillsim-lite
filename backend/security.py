"""Secret handling: detect and redact API keys anywhere text is stored, logged, or shown."""

from __future__ import annotations

import os
import re

SECRET_ENV_NAMES = ("PORTKEY_API_KEY", "OPENAI_API_KEY")
# Common key shapes, so a pasted key is caught even if it isn't this server's own key.
SECRET_PATTERNS = re.compile(r"\b(sk-(?:proj-)?[A-Za-z0-9_\-]{16,}|pk-[A-Za-z0-9_\-]{16,})\b")
REDACTED = "[REDACTED]"


def _secret_values() -> list[str]:
    return [v for v in (os.getenv(n, "").strip() for n in SECRET_ENV_NAMES) if len(v) >= 8]


def contains_secret(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return any(v in text for v in _secret_values()) or bool(SECRET_PATTERNS.search(text))


def redact(value):
    """Return a copy with every secret value or key-shaped string replaced. Works on nested data."""
    if isinstance(value, str):
        for v in _secret_values():
            value = value.replace(v, REDACTED)
        return SECRET_PATTERNS.sub(REDACTED, value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value
