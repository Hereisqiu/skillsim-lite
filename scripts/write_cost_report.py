"""Write exports/cost_optimization.md from the benchmark exports (numbers are computed, never typed).

The latest benchmark is the main comparison and covers every variant it ran. Earlier benchmark
files are summarized afterwards, each compared only within its own run.

    python -m scripts.write_cost_report
"""

from __future__ import annotations

import csv
import glob
import json
import math
import statistics as st

from backend import config

METRICS = ("requests", "input_tokens", "cached_input_tokens", "output_tokens", "cost_usd", "quality_score")


def load(path: str) -> dict:
    d = json.load(open(path))
    d["path"] = path
    d["requests_rows"] = sorted(csv.DictReader(open(path.replace(".json", "_requests.csv"))), key=lambda r: float(r["ts"]))
    d["comparison"] = normalize_comparison(d.get("comparison"))
    return d


def normalize_comparison(c: dict | None) -> dict | None:
    """Older exports stored a single baseline-vs-optimized comparison; convert it to the general form."""
    if not c or "reference" in c:
        return c
    return {"reference": "baseline", "variants": {"optimized": {
        m: {"reference_mean": v["baseline_mean"], "mean": v["optimized_mean"], "change_pct": v["change_pct"]}
        for m, v in c.items()}}}


def lookup_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["agent"] == "roleplay" and r["tool_calls"]]


def difference(sims: list[dict], ref: str, v: str, key: str = "input_tokens") -> dict:
    """Mean difference (v - ref) with its standard error; 'clear' when it exceeds two standard errors."""
    a = [s[key] for s in sims if s["variant"] == ref]
    b = [s[key] for s in sims if s["variant"] == v]
    se = math.sqrt(st.variance(a) / len(a) + st.variance(b) / len(b)) if len(a) > 1 and len(b) > 1 else float("nan")
    diff = st.mean(b) - st.mean(a)
    return {"diff": diff, "se": se, "clear": abs(diff) > 2 * se, "pct": 100 * diff / st.mean(a)}


def per_session_lookups(d: dict, variant: str) -> float:
    sids = {s["session_id"] for s in d["simulations"] if s["variant"] == variant}
    ok = [r for r in d["requests_rows"] if not r["error"] and r["session_id"] in sids]
    return len(lookup_rows(ok)) / len(sids)


def variant_table(d: dict, out: list[str]) -> None:
    sims, variants, c = d["simulations"], list(d["by_variant"]), d.get("comparison")
    out.append("| Variant | Runs | Requests | Lookup-only requests | Input tokens (sd) | Cached input | Output tokens | Cost (USD) | Quality (of 5) |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for v in variants:
        xs = [s for s in sims if s["variant"] == v]
        sd = st.stdev([s["input_tokens"] for s in xs]) if len(xs) > 1 else 0
        b = d["by_variant"][v]
        out.append(f"| {v} | {b['runs']} | {b['requests']['mean']:.1f} | {per_session_lookups(d, v):.1f} | "
                   f"{b['input_tokens']['mean']:,.0f} (±{sd:,.0f}) | {b['cached_input_tokens']['mean']:,.0f} | "
                   f"{b['output_tokens']['mean']:,.0f} | {b['cost_usd']['mean']:.5f} | {b['quality_score']['mean']:.2f} |")
    if c:
        ref = c["reference"]
        for v, m in c["variants"].items():
            lk_ref, lk_v = per_session_lookups(d, ref), per_session_lookups(d, v)
            lk = f"{100 * (lk_v - lk_ref) / lk_ref:+.1f}%" if lk_ref else ""
            out.append(f"| {v} vs {ref} | | {m['requests']['change_pct']:+.1f}% | {lk} | {m['input_tokens']['change_pct']:+.1f}% | "
                       f"{m['cached_input_tokens']['change_pct']:+.1f}% | {m['output_tokens']['change_pct']:+.1f}% | "
                       f"{m['cost_usd']['change_pct']:+.1f}% | {m['quality_score']['change_pct']:+.1f}% |")


def main_cli():
    paths = sorted(glob.glob(str(config.ROOT / "exports" / "bench-*.json")))
    d = load(paths[-1])
    earlier = [load(p) for p in reversed(paths[:-1])]
    sims, variants, c = d["simulations"], list(d["by_variant"]), d.get("comparison")
    rows = [r for r in d["requests_rows"] if not r["error"]]
    pricing = d["pricing"]

    out = [f"# Cost optimization: measured comparison\n",
           f"Source: `{d['path'].split('/')[-1]}` (run {d['run_tag']}, model {d['model']}). All numbers below are computed "
           "from the benchmark exports by `scripts/write_cost_report.py`.\n",
           "## Method\n", d["method"]["description"] + "\n"]
    for v, desc in d["method"]["variants"].items():
        out.append(f"- **{v}**: {desc}")
    out.append(f"\nRuns: {len(sims)} ({d['method']['reps_per_scenario_per_variant']} per scenario per variant). "
               f"All runs fresh (no gateway cache hits): {all(s['fresh'] for s in sims)}.\n")
    cached_note = ("Cached tokens are billed at the input rate (no cached rate is published), so prompt caching lowers "
                   "latency but not the cost shown here." if pricing.get("cached_input") is None
                   else "Cached tokens are billed at the cached-input rate.")
    out.append(f"Prices: {config.PRICING['units']}; " + json.dumps({k: pricing[k] for k in ('input', 'cached_input', 'output')})
               + f". Source: {pricing['source']} (as of {pricing['as_of']}). {cached_note}\n")

    out.append("## Per full simulation (conversation + feedback), mean of measured runs\n")
    out.append("\"Lookup-only requests\" are roleplay requests whose only output is a `get_scenario_facts` call.\n")
    variant_table(d, out)

    out.append("\n## By scenario (input tokens per run)\n")
    out.append("| Scenario | " + " | ".join(variants) + " |")
    out.append("|---|" + "---|" * len(variants))
    for sc in d["by_scenario"]:
        cells = []
        for v in variants:
            xs = [s["input_tokens"] for s in sims if s["scenario_id"] == sc and s["variant"] == v]
            cells.append(", ".join(f"{x:,}" for x in xs) + f" (mean {st.mean(xs):,.0f})" if xs else "")
        out.append(f"| {sc} | " + " | ".join(cells) + " |")

    out.append("\n## Where the tokens go, by variant\n")
    out.append("| Variant | Request type | Requests | Input tokens | Share of variant's input | Output tokens | Cost (USD) |")
    out.append("|---|---|---|---|---|---|---|")
    for v in variants:
        vr = [r for r in rows if r["variant"] == v]
        total_in = sum(int(r["input_tokens"]) for r in vr)
        groups = {
            "Roleplay, only a tool call": lookup_rows(vr),
            "Roleplay, the reply": [r for r in vr if r["agent"] == "roleplay" and not r["tool_calls"]],
            "Feedback": [r for r in vr if r["agent"] == "feedback"],
        }
        for name, g in groups.items():
            i = sum(int(r["input_tokens"]) for r in g)
            out.append(f"| {v} | {name} | {len(g)} | {i:,} | {100 * i / total_in:.0f}% | "
                       f"{sum(int(r['output_tokens']) for r in g):,} | {sum(float(r['cost_usd']) for r in g):.4f} |")
    out.append("")
    for v in variants:
        vr = [r for r in rows if r["variant"] == v]
        cached = sum(int(r["cached_input_tokens"] or 0) for r in vr)
        out.append(f"- {v}: cached share of input tokens (as reported by the API) {100 * cached / sum(int(r['input_tokens']) for r in vr):.1f}%.")

    out.append("\n## First request of each session\n")
    out.append("Same scenario, opening line and first user message in every variant. Between baseline and optimized "
               "only the packing differs; prefetch also carries every curated fact in the static scenario message.\n")
    first = {}
    for r in d["requests_rows"]:
        if not r["error"]:
            first.setdefault(r["session_id"], r)
    controlled = {}
    for r in first.values():
        controlled.setdefault(r["scenario_id"], {}).setdefault(r["variant"], []).append(r)
    out.append("| Scenario | " + " | ".join(f"{v} input tokens (calls a tool?)" for v in variants) + " |")
    out.append("|---|" + "---|" * len(variants))
    for sc, by_v in controlled.items():
        cells = [", ".join(f"{r['input_tokens']} ({'yes' if r['tool_calls'] else 'no'})" for r in by_v.get(v, [])) for v in variants]
        out.append(f"| {sc} | " + " | ".join(cells) + " |")

    out.append("\n## Quality rubric (deterministic, 1 point each)\n")
    for k, v in d["method"]["quality_rubric"].items():
        out.append(f"- **{k}**: {v}")
    out.append("\n| Variant | " + " | ".join(d["method"]["quality_rubric"]) + " |")
    out.append("|---|" + "---|" * len(d["method"]["quality_rubric"]))
    for v in variants:
        xs = [s for s in sims if s["variant"] == v]
        out.append(f"| {v} | " + " | ".join(f"{sum(s['quality']['checks'][k] for s in xs)}/{len(xs)}"
                                           for k in d["method"]["quality_rubric"]) + " |")
    fb = {v: [s["feedback_score"] for s in sims if s["variant"] == v] for v in variants}
    out.append("\nFeedback scores the coach gave each run (same scripted user turns): "
               + "; ".join(f"{v}: {fb[v]} (mean {st.mean(fb[v]):.1f})" for v in variants) + ".\n")

    if earlier:
        out.append("## Earlier benchmark runs\n")
        out.append("Each earlier run is compared only within itself (same day, same conditions).\n")
        for e in earlier:
            out.append(f"### `{e['path'].split('/')[-1]}`\n")
            variant_table(e, out)
            ec = e.get("comparison")
            if ec:
                for v in ec["variants"]:
                    x = difference(e["simulations"], ec["reference"], v)
                    out.append(f"\n{v} vs {ec['reference']}: {x['diff']:+,.0f} input tokens per session ({x['pct']:+.1f}%), "
                               f"standard error {x['se']:,.0f}: " + ("a clear difference." if x["clear"] else "within run-to-run noise."))
            out.append("")

    if c:
        ref = c["reference"]
        out.append("## Conclusion\n")
        out.append(f"A difference counts as measured only if it is larger than two standard errors of the difference "
                   f"between the two variants' session means ({len(sims) // len(variants)} sessions each).\n")
        for v, m in c["variants"].items():
            x = difference(sims, ref, v)
            y = difference(sims, ref, v, "cost_usd")
            q = m["quality_score"]
            out.append(f"- **{v} vs {ref}**: input tokens {x['diff']:+,.0f} per session ({x['pct']:+.1f}%, standard error "
                       f"{x['se']:,.0f}), " + ("a clear difference" if x["clear"] else "within run-to-run noise")
                       + f"; cost {y['pct']:+.1f}% per session (" + ("clear" if y["clear"] else "within noise")
                       + f"); requests per session {m['requests']['reference_mean']:.1f} → {m['requests']['mean']:.1f}; "
                       f"lookup-only requests per session {per_session_lookups(d, ref):.1f} → {per_session_lookups(d, v):.1f}; "
                       f"rubric quality {q['reference_mean']:.2f} → {q['mean']:.2f} of 5.")
        out.append("\nThe rubric checks format and numbers, not whether the character reveals hidden information too early; "
                   "that needs a reading of the transcripts (see the benchmark JSON, `transcripts`).\n")

    target = config.ROOT / "exports" / "cost_optimization.md"
    target.write_text("\n".join(out))
    print(f"Wrote {target}")


if __name__ == "__main__":
    main_cli()
