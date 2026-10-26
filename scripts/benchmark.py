"""Reproducible cost benchmark: real end-to-end simulations through the app's own API.

Runs every scenario with the same scripted user turns under each context mode, then exports
measured token counts (from the API's usage data), costs, and the quality rubric.

    python -m scripts.benchmark                      # baseline vs optimized, 2 reps per scenario
    python -m scripts.benchmark --reps 1 --variants optimized
    python -m scripts.benchmark --reps 3 --variants optimized prefetch

Uses the real model and costs real money (about $0.002 per run). Outputs go to exports/.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import os

os.environ["SKILLSIM_GATEWAY_CACHE_REFRESH"] = "1"  # measure fresh model calls, never gateway replays

from fastapi.testclient import TestClient  # noqa: E402

from backend import config, ledger, main, measure, store  # noqa: E402

EXPORTS = config.ROOT / "exports"

# Fixed user turns: a competent-but-imperfect user, identical for every variant.
SCRIPTS = {
    "tough-feedback": [
        "Hi Jordan. I wanted to talk about the last three sprints. The checkout mockups came in late each time, and engineering is now blocked on saved carts. What's been going on from your side?",
        "Okay. I'm not here to judge you, it sounds like a lot is landing on you. What's actually been taking up your time?",
        "That makes sense, and I wish I'd known sooner. How about I talk to Dana and get the rebrand work into sprint planning, and you focus on Thursday's saved-carts handoff?",
        "Great. So I'll talk to Dana by tomorrow, and you'll get me the saved-carts mockups by Thursday. Let's check in Wednesday afternoon. Sound good?",
    ],
    "salary-negotiation": [
        "Hi Priya, thanks so much. I'm really excited about the role and the team. I did want to talk about the base salary before I give you a final answer.",
        "Based on my research, comparable Senior Analyst roles here pay between $100,000 and $108,000. Given my forecasting experience, I was hoping for a base of $105,000.",
        "I understand the equity concern. What flexibility do you have on base, and are there other parts of the package we could look at?",
        "If base can go to $101,000, could you add a signing bonus and a written six-month review? If so, I can give you a verbal yes by Friday.",
    ],
    "upset-client": [
        "You're right to be upset, and I'm sorry. This one's on us: a bug in our integration with your scheduling system was caught in final testing and pushed your launch.",
        "Our engineers found the root cause and expect the fix verified by Thursday. I'd like to show you a working demo on staging Friday.",
        "I'll send you a written summary today by 5 p.m. that you can forward to your CEO. Can we check in Wednesday at 10?",
        "For the go/no-go, I'll own that decision with our engineering lead, and if Thursday's verification fails we'll tell you the same day and agree a new date together before anything goes to patients.",
    ],
}


def run_one(client: TestClient, scenario_id: str, variant: str, run_tag: str) -> str:
    config.CONTEXT_MODE = variant
    r = client.post("/api/sessions", json={"scenario_id": scenario_id})
    r.raise_for_status()
    sid = r.json()["id"]
    session = store.get(sid)
    session["run_tag"] = run_tag
    session["variant"] = variant
    store.put(session)
    for line in SCRIPTS[scenario_id]:
        time.sleep(config.MIN_SECONDS_BETWEEN_MESSAGES)
        r = client.post(f"/api/sessions/{sid}/messages", json={"text": line})
        if r.status_code != 200:
            print(f"   ! {scenario_id}/{variant}: message failed {r.status_code} {r.text[:120]}")
    r = client.post(f"/api/sessions/{sid}/end")
    if r.status_code != 200:
        print(f"   ! {scenario_id}/{variant}: feedback failed {r.status_code} {r.text[:120]}")
    return sid


def pct_change(base, new):
    if base in (None, 0) or new is None:
        return None
    return round(100 * (new - base) / base, 1)


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="+", default=["baseline", "optimized"], choices=list(config.CONTEXT_MODES))
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--scenarios", nargs="+", default=list(SCRIPTS))
    args = ap.parse_args()

    if main.engine is None or main.engine.source != "live":
        raise SystemExit(f"The live model isn't configured: {main.engine_error}")

    run_tag = "bench-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    client = TestClient(main.app, headers={"X-SkillSim-Client": f"benchmark-{run_tag}"})
    session_ids = []
    for rep in range(args.reps):
        # Alternate variant order each rep so time-of-day effects don't favor one variant.
        order = args.variants if rep % 2 == 0 else list(reversed(args.variants))
        for scenario_id in args.scenarios:
            for variant in order:
                t0 = time.time()
                sid = run_one(client, scenario_id, variant, run_tag)
                session_ids.append(sid)
                print(f"rep {rep + 1} {scenario_id:20} {variant:9} session {sid}  {time.time() - t0:5.1f}s", flush=True)

    sessions = [store.get(sid) for sid in session_ids]
    rows = [r for r in ledger.read_all() if r.get("session_id") in set(session_ids)]
    sims = measure.simulations(sessions, rows, main.SCENARIOS_BY_ID)
    stale = [x["session_id"] for x in sims if not x["fresh"]]
    if stale:
        print(f"   ! {len(stale)} runs had gateway cache hits and are excluded: {stale}")
    sims = [x for x in sims if x["fresh"]]
    by_variant = {v: measure.summarize([s for s in sims if s["variant"] == v]) for v in args.variants}
    by_scenario = {
        sc: {v: measure.summarize([s for s in sims if s["variant"] == v and s["scenario_id"] == sc]) for v in args.variants}
        for sc in args.scenarios
    }
    # Every other variant is compared with the reference: the first of baseline/optimized/prefetch that ran.
    comparison = None
    if len(args.variants) > 1:
        ref = next(v for v in config.CONTEXT_MODES if v in args.variants)
        b = by_variant[ref]
        comparison = {"reference": ref, "variants": {
            v: {metric: {"reference_mean": b[metric]["mean"], "mean": o[metric]["mean"],
                         "change_pct": pct_change(b[metric]["mean"], o[metric]["mean"])}
                for metric in ("input_tokens", "cached_input_tokens", "output_tokens", "requests", "cost_usd", "quality_score")
                if b.get(metric) and o.get(metric)}
            for v, o in by_variant.items() if v != ref}}

    EXPORTS.mkdir(exist_ok=True)
    out = {
        "run_tag": run_tag,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": main.engine.model,
        "pricing": config.price_for(main.engine.model),
        "method": {
            "description": "Each scenario was run with identical scripted user turns under each context mode, with Portkey's "
                           "response cache bypassed (x-portkey-cache-force-refresh) so every request is a fresh model call. "
                           "Token counts are the API's reported usage, summed per session (all roleplay turns + feedback). "
                           "Decode is excluded (it is cached per scenario).",
            "variants": {k: desc for k, desc in {
                "baseline": "Original packing: indented JSON for scenario data, transcript, and tool results; every earlier tool lookup replayed in history.",
                "optimized": "Compact JSON (no indentation) for the same content; repeat lookups of an already-replayed fact are dropped from history; the redundant fact-topic list is removed (the tool's enum already lists the topics).",
                "prefetch": "Optimized, plus every curated character fact placed in the static SCENARIO DATA message (a cacheable prefix), so the character rarely needs a get_scenario_facts round; the tool stays available.",
            }.items() if k in args.variants},
            "reps_per_scenario_per_variant": args.reps,
            "user_turns_per_run": {k: len(v) for k, v in SCRIPTS.items() if k in args.scenarios},
            "quality_rubric": measure.RUBRIC,
        },
        "comparison": comparison,
        "by_variant": by_variant,
        "by_scenario": by_scenario,
        "simulations": sims,
        "transcripts": {s["id"]: {"scenario": s["scenario_id"], "variant": s["variant"],
                                  "messages": [{"role": m["role"], "text": m["text"]} for m in s["messages"]],
                                  "feedback_score": (s.get("feedback") or {}).get("overall")} for s in sessions},
    }
    base = EXPORTS / run_tag
    Path(f"{base}.json").write_text(json.dumps(out, indent=2))
    Path(f"{base}_simulations.csv").write_text(measure.simulations_csv(sims))
    Path(f"{base}_requests.csv").write_text(measure.requests_csv(rows))
    print(f"\nWrote {base}.json, _simulations.csv, _requests.csv")
    print(json.dumps({"by_variant": {v: {k: (by_variant[v][k] or {}).get("mean") if isinstance(by_variant[v].get(k), dict) else by_variant[v].get(k)
                                         for k in ("runs", "input_tokens", "cached_input_tokens", "output_tokens", "requests", "cost_usd", "quality_score")}
                                     for v in by_variant}, "comparison": comparison}, indent=1))


if __name__ == "__main__":
    main_cli()
