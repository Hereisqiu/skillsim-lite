"""App settings and .env loading.

The .env is looked up in the repo folder first, then one folder above it
(the teaching staff keep theirs in the parent `submissions/` folder).

Exactly one model path is used, chosen by SKILLSIM_PROVIDER:
  portkey (default): PORTKEY_API_KEY + gpt-6-luna via the course Portkey gateway
  openai:            OPENAI_API_KEY + the model named in OPENAI_MODEL (your own account)
The two are never mixed and there is no fallback from one to the other.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FRONTEND_DIR = ROOT / "frontend"

ENV_CANDIDATES = [ROOT / ".env", ROOT.parent / ".env"]


def load_env() -> list[Path]:
    """Load the project's .env first, then the parent folder's for anything still missing.
    Earlier sources win: real environment variables, then the project .env, then the parent .env."""
    found = []
    for path in ENV_CANDIDATES:
        if path.is_file():
            load_dotenv(path, override=False)
            found.append(path)
    return found


ENV_PATHS = load_env()
ENV_PATH = ENV_PATHS[0] if ENV_PATHS else None

# "live" calls the model; "mock" is the scripted demo engine (must be chosen explicitly).
ENGINE = os.getenv("SKILLSIM_ENGINE", "live").strip().lower()
PROVIDER = os.getenv("SKILLSIM_PROVIDER", "portkey").strip().lower()

PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
COURSE_MODEL = "gpt-6-luna"

# All prices live in pricing.json (source, units, date). Nothing is hardcoded here.
PRICING_FILE = ROOT / "pricing.json"
PRICING: dict = json.loads(PRICING_FILE.read_text())


def price_for(model: str | None) -> dict | None:
    """Prices for a model from pricing.json, or None if the model isn't listed (cost = unavailable)."""
    return PRICING["models"].get(model) if model else None


# Portkey can answer identical requests from its own response cache. Set to 1 to force fresh
# model calls (the benchmark does this so its token counts reflect real generations).
GATEWAY_CACHE_REFRESH = os.getenv("SKILLSIM_GATEWAY_CACHE_REFRESH", "0") == "1"

# Context packing for the agents. "optimized" sends compact JSON and replays each looked-up fact
# only once; "baseline" is the original packing; "prefetch" is optimized plus the character's curated
# facts placed in the static SCENARIO DATA message, so the roleplay agent rarely needs a lookup round
# (get_scenario_facts stays available). See exports/ for the measured comparison.
CONTEXT_MODES = ("baseline", "optimized", "prefetch")
CONTEXT_MODE = os.getenv("SKILLSIM_CONTEXT", "optimized").strip().lower()


def compact_context() -> bool:
    """Compact JSON and deduplicated lookups (every mode except baseline)."""
    return CONTEXT_MODE in ("optimized", "prefetch")


def provider_settings() -> dict:
    """Resolve the one model path in use. Raises ValueError if it is misconfigured."""
    if PROVIDER == "portkey":
        key = os.getenv("PORTKEY_API_KEY", "").strip()
        if not key:
            raise ValueError("PORTKEY_API_KEY is missing. Add it to .env in this folder or the folder above.")
        return {
            "provider": "portkey",
            "api_key": key,
            "base_url": PORTKEY_BASE_URL,
            "headers": {"x-portkey-api-key": key},
            "model": COURSE_MODEL,
            "prices": price_for(COURSE_MODEL),
        }
    if PROVIDER == "openai":
        key = os.getenv("OPENAI_API_KEY", "").strip()
        model = os.getenv("OPENAI_MODEL", "").strip()
        if not key:
            raise ValueError("SKILLSIM_PROVIDER=openai but OPENAI_API_KEY is missing.")
        if not model:
            raise ValueError("SKILLSIM_PROVIDER=openai needs OPENAI_MODEL set to the model you will pay for.")
        return {"provider": "openai", "api_key": key, "base_url": None, "headers": {}, "model": model,
                "prices": price_for(model)}
    raise ValueError(f"Unknown SKILLSIM_PROVIDER '{PROVIDER}'. Use 'portkey' or 'openai'.")


def describe_provider() -> dict:
    """Browser-safe description of the model path. Never includes a key."""
    if ENGINE == "mock":
        return {"engine": "mock", "provider": None, "model": None, "ready": True, "error": None, "prices": price_for(COURSE_MODEL)}
    try:
        s = provider_settings()
        return {"engine": "live", "provider": s["provider"], "model": s["model"], "ready": True, "error": None, "prices": s["prices"]}
    except ValueError as exc:
        return {"engine": "live", "provider": PROVIDER, "model": None, "ready": False, "error": str(exc), "prices": None}


def cost_usd(prices: dict | None, input_tokens: int, cached_input_tokens: int | None, output_tokens: int) -> float | None:
    """USD for one or more calls. None if the model has no listed price. When the cached-input rate
    is unknown (null), or cached tokens weren't reported, cached tokens are billed at the input rate."""
    if not prices:
        return None
    cached = cached_input_tokens or 0
    cached_rate = prices["cached_input"] if prices.get("cached_input") is not None else prices["input"]
    uncached = max(input_tokens - cached, 0)
    return (uncached * prices["input"] + cached * cached_rate + output_tokens * prices["output"]) / 1_000_000


def cost_basis(prices: dict | None) -> str:
    if not prices:
        return "unavailable: model not in pricing.json"
    if prices.get("cached_input") is None:
        return "upper bound: cached tokens billed at input rate (cached rate not published)"
    return "pricing.json rates"


# ---- conversation limits ----
MAX_USER_TURNS = 12
MAX_MESSAGE_CHARS = 1200
SESSION_IDLE_TIMEOUT_MIN = 30
MIN_SECONDS_BETWEEN_MESSAGES = 1.0
MAX_CONTEXT_MESSAGES = 24          # older turns are dropped (opening line always kept)

# ---- model call limits ----
REQUEST_TIMEOUT_S = 45
MAX_RETRIES = 2                    # transient failures only (timeouts, 429, 5xx)
MAX_TOOL_ROUNDS = 2                # tool calls per turn before the agent must answer
ROLEPLAY_MAX_OUTPUT_TOKENS = 400
FEEDBACK_MAX_OUTPUT_TOKENS = 1800
DECODE_MAX_OUTPUT_TOKENS = 1500

# ---- spend protection ----
SESSION_TOKEN_BUDGET = 80_000      # all calls in one practice session
DAILY_TOKEN_BUDGET = 2_000_000     # whole app, per UTC day
DAILY_COST_BUDGET_USD = 1.00       # whole app, per UTC day (when prices are known)

# Developer trace view (tool calls, retries, guardrail events). Set to 0 to hide.
DEV_TOOLS = os.getenv("SKILLSIM_DEV_TOOLS", "1") != "0"
