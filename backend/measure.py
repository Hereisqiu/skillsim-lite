"""Measurements from the request ledger, plus clearly separated projections.

MEASURED  = summed from data/requests.jsonl, i.e. usage numbers the API returned.
PROJECTED = measured averages multiplied by stated assumptions. Never mixed into measured totals.
"""

from __future__ import annotations

import csv
import io
import json
import re
import statistics
from difflib import SequenceMatcher

from . import config, ledger
from .agents import BROKE_CHARACTER

DEFAULT_SESSIONS_PER_USER_MONTH = 8   # assumption: two practice sessions a week
FRESH = {"MISS", "REFRESH"}           # Portkey cache statuses that mean a new model call was made


# ---------- measured ----------

def aggregate(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("error") is None]
    cached_reported = [r for r in ok if r.get("cached_input_tokens") is not None]
    costs = [r["cost_usd"] for r in ok if r.get("cost_usd") is not None]
    latencies = [r["latency_ms"] for r in ok]
    input_tokens = sum(r["input_tokens"] for r in ok)
    return {
        "requests": len(ok),
        "failed_requests": len(rows) - len(ok),
        "input_tokens": input_tokens,
        # Null when no request reported a cached count; otherwise the sum of the ones that did.
        "cached_input_tokens": sum(r["cached_input_tokens"] for r in cached_reported) if cached_reported else None,
        "cached_unreported_requests": len(ok) - len(cached_reported),
        "cache_hit_rate": (round(sum(r["cached_input_tokens"] for r in cached_reported) / input_tokens, 4)
                           if cached_reported and input_tokens else None),
        "output_tokens": sum(r["output_tokens"] for r in ok),
        "cost_usd": round(sum(costs), 6) if len(costs) == len(ok) else None,
        "tool_calls": sum(len(r.get("tool_calls") or []) for r in ok),
        "avg_latency_ms": round(statistics.mean(latencies)) if latencies else None,
        "gateway_cache_hits": sum(1 for r in ok if r.get("gateway_cache") == "HIT"),
        "gateway_cache_unknown": sum(1 for r in ok if r.get("gateway_cache") is None),
        "total_latency_ms": sum(latencies),
    }


def group_by(rows: list[dict], key: str) -> dict:
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r.get(key) or "none", []).append(r)
    return {k: aggregate(v) for k, v in sorted(groups.items())}


def simulations(sessions: list[dict], rows: list[dict], scenarios: dict) -> list[dict]:
    """One record per completed live session that has ledger rows: the cost of a full simulation + feedback."""
    by_session: dict[str, list] = {}
    for r in rows:
        if r.get("session_id"):
            by_session.setdefault(r["session_id"], []).append(r)
    out = []
    for s in sessions:
        session_rows = by_session.get(s["id"])
        if not session_rows or not s.get("feedback") or s.get("engine") == "mock":
            continue
        agg = aggregate(session_rows)
        # "Fresh" = every request was a confirmed new model call (gateway cache MISS, or REFRESH when forced).
        fresh = all(r.get("gateway_cache") in FRESH for r in session_rows if r.get("error") is None)
        out.append({
            "session_id": s["id"], "scenario_id": s["scenario_id"], "attempt": s["attempt"],
            "variant": s.get("variant", "baseline"), "run_tag": s.get("run_tag"), "started_at": s["started_at"],
            "user_turns": sum(1 for m in s["messages"] if m["role"] == "user"),
            "feedback_score": s["feedback"].get("overall"),
            "roleplay": aggregate([r for r in session_rows if r["agent"] == "roleplay"]),
            "feedback": aggregate([r for r in session_rows if r["agent"] == "feedback"]),
            **{k: agg[k] for k in ("requests", "failed_requests", "input_tokens", "cached_input_tokens",
                                   "output_tokens", "cost_usd", "tool_calls", "total_latency_ms")},
            "quality": quality(s, scenarios.get(s["scenario_id"])),
            "fresh": fresh,
            "gateway_cache_hits": agg["gateway_cache_hits"],
            "gateway_cache_unknown": agg["gateway_cache_unknown"],
        })
    return out


def summarize(sims: list[dict]) -> dict:
    if not sims:
        return {"runs": 0}

    def stats(values):
        values = [v for v in values if v is not None]
        if not values:
            return None
        values = sorted(values)
        p90 = values[min(len(values) - 1, round(0.9 * (len(values) - 1)))]
        return {"mean": round(statistics.mean(values), 6), "median": round(statistics.median(values), 6),
                "min": values[0], "max": values[-1], "p90": p90}

    return {
        "runs": len(sims),
        "cost_usd": stats([s["cost_usd"] for s in sims]),
        "input_tokens": stats([s["input_tokens"] for s in sims]),
        "cached_input_tokens": stats([s["cached_input_tokens"] for s in sims]),
        "output_tokens": stats([s["output_tokens"] for s in sims]),
        "requests": stats([s["requests"] for s in sims]),
        "user_turns": stats([s["user_turns"] for s in sims]),
        "quality_score": stats([s["quality"]["score"] for s in sims]),
    }


# ---------- quality rubric ----------

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in NUMBER.findall(text)}


def quality(session: dict, scenario: dict | None) -> dict:
    """Simple deterministic rubric (5 checks, 1 point each), applied identically to every run."""
    replies = [m["text"] for m in session["messages"] if m["role"] == "ai" and m.get("source") == "live"]
    user_text = " ".join(m["text"] for m in session["messages"] if m["role"] == "user")
    trace_rules = {e["detail"].get("rule") for e in session.get("trace", []) if e["event"] == "guardrail"}

    known = _numbers(json.dumps(scenario or {}) + " " + user_text)
    invented = sorted({n for r in replies for n in _numbers(r)
                       if n not in known and str(int(float(n)) * 1000) not in known})
    similarity = max((SequenceMatcher(None, a, b).ratio() for i, a in enumerate(replies) for b in replies[i + 1:]), default=0)
    fb = session.get("feedback") or {}
    feedback_complete = all([fb.get("what_happened"), (fb.get("opportunity") or {}).get("description"),
                             (fb.get("alternative") or {}).get("response"), fb.get("retry_challenge")])

    checks = {
        "in_character": "output_check" not in trace_rules and not any(BROKE_CHARACTER.search(r) for r in replies),
        "facts_consistent": not invented,
        "concise": all(len(r.split()) <= 90 for r in replies),
        "varied": similarity < 0.6,
        "feedback_grounded": feedback_complete and not ({"schema_validation", "unverified_quote"} & trace_rules),
    }
    return {"score": sum(checks.values()), "max": len(checks), "checks": checks,
            "details": {"numbers_not_in_scenario": invented, "max_reply_similarity": round(similarity, 3),
                        "max_reply_words": max((len(r.split()) for r in replies), default=0)}}


RUBRIC = {
    "in_character": "No reply broke character, and the output guard never had to regenerate.",
    "facts_consistent": "Every number the character said appears in the scenario data or the user's own words.",
    "concise": "Every character reply is 90 words or fewer.",
    "varied": "No two character replies are more than 60% similar (difflib ratio).",
    "feedback_grounded": "Feedback has all parts, validated on the first try, with no fabricated quotes removed.",
}


# ---------- projections ----------

def projections(sims_summary: dict, decode: dict, sessions_per_user_month: float) -> dict | None:
    cost = sims_summary.get("cost_usd") if sims_summary.get("runs") else None
    if not cost:
        return None
    decode_once = decode.get("cost_usd") or 0.0

    def scale(users, per_session):
        return round(users * sessions_per_user_month * per_session + decode_once, 4)

    return {
        "assumptions": [
            f"Each user completes {sessions_per_user_month:g} full practice sessions (conversation + feedback) per month.",
            f"Cost per session = the measured mean across {sims_summary['runs']} real runs (${cost['mean']:.5f}); "
            f"the high estimate uses the measured p90 (${cost['p90']:.5f}).",
            ("Decode This Situation is generated once per scenario and cached for everyone, so its measured "
             f"cost (${decode_once:.5f} across {decode.get('requests', 0)} requests) is added once, not per user."
             if decode.get("requests") else
             "Decode This Situation is generated once per scenario and cached; its cost is not yet in the ledger, "
             "so it is not included."),
            "Prices from pricing.json. Cached input tokens are billed at the full input rate (cached rate unpublished), "
            "so real costs may be lower.",
            "Excludes hosting, storage, and any free-tier or volume discounts.",
        ],
        "sessions_per_user_month": sessions_per_user_month,
        "per_user_month": {"mean": round(sessions_per_user_month * cost["mean"], 5),
                           "high": round(sessions_per_user_month * cost["p90"], 5)},
        "users_100": {"mean": scale(100, cost["mean"]), "high": scale(100, cost["p90"])},
        "users_10000": {"mean": scale(10_000, cost["mean"]), "high": scale(10_000, cost["p90"])},
    }


# ---------- report ----------

def report(sessions: list[dict], scenarios: dict, sessions_per_user_month: float = DEFAULT_SESSIONS_PER_USER_MONTH,
           request_limit: int = 200) -> dict:
    rows = [r for r in ledger.read_all() if r.get("model")]
    all_sims = simulations(sessions, rows, scenarios)
    sims = [s for s in all_sims if s["fresh"]]
    decode_rows = [r for r in rows if r["agent"] == "decode"]
    by_variant = {}
    for v in sorted({s["variant"] for s in sims}):
        by_variant[v] = summarize([s for s in sims if s["variant"] == v])
    overall = summarize(sims)
    decode = aggregate(decode_rows)
    return {
        "pricing": {"file": "pricing.json", "units": config.PRICING["units"], "models": config.PRICING["models"]},
        "measured": {
            "note": "Sums of token counts returned by the API for each request (data/requests.jsonl).",
            "all_requests": aggregate(rows),
            "by_agent": group_by(rows, "agent"),
            "by_operation": group_by(rows, "operation"),
            "decode": decode,
            "simulations": all_sims,
            "simulation_summary": overall,
            "summary_basis": (f"Averages use {len(sims)} fresh simulations (every request a confirmed new model call). "
                              f"{len(all_sims) - len(sims)} other simulations are listed but excluded because some "
                              "requests were gateway cache hits or were logged before cache status was recorded."),
            "by_variant": by_variant,
            "requests": rows[-request_limit:][::-1],
        },
        "quality_rubric": RUBRIC,
        "projected": projections(overall, decode, sessions_per_user_month),
    }


def simulations_csv(sims: list[dict]) -> str:
    cols = ["session_id", "scenario_id", "variant", "run_tag", "fresh", "gateway_cache_hits", "attempt", "user_turns", "requests", "failed_requests",
            "input_tokens", "cached_input_tokens", "output_tokens", "tool_calls", "cost_usd", "total_latency_ms",
            "roleplay_input_tokens", "roleplay_output_tokens", "feedback_input_tokens", "feedback_output_tokens",
            "feedback_score", "quality_score", *[f"q_{k}" for k in RUBRIC]]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for s in sims:
        w.writerow({**{k: s.get(k) for k in cols if k in s},
                    "roleplay_input_tokens": s["roleplay"]["input_tokens"], "roleplay_output_tokens": s["roleplay"]["output_tokens"],
                    "feedback_input_tokens": s["feedback"]["input_tokens"], "feedback_output_tokens": s["feedback"]["output_tokens"],
                    "quality_score": s["quality"]["score"], **{f"q_{k}": int(v) for k, v in s["quality"]["checks"].items()}})
    return buf.getvalue()


def requests_csv(rows: list[dict]) -> str:
    cols = ["ts", "request_id", "session_id", "scenario_id", "variant", "run_tag", "model", "agent", "operation",
            "attempt", "status", "error", "input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens",
            "reasoning_tokens", "latency_ms", "cost_usd", "cost_basis", "gateway_cache", "routed_provider", "tool_calls"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({**r, "tool_calls": ";".join(r.get("tool_calls") or [])})
    return buf.getvalue()
