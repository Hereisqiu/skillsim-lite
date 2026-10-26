"""Summarize real evaluation data. It never invents or fills in values.

    python -m scripts.summarize_evaluation

Reads evaluation/participant_data.csv and evaluation/comparison_ratings.csv (copies of the
templates, filled in during sessions) and writes evaluation/results_summary.md.
Only rows with consent_data = yes are counted. Feedback is quoted only with consent_quote = yes.
"""

from __future__ import annotations

import argparse
import csv
import statistics as st
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend import config

EVAL_DIR = config.ROOT / "evaluation"
YES_NO = {"yes", "no"}


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def _num(value: str, lo=None, hi=None, integer=False):
    if value == "":
        return None
    n = int(value) if integer else float(value)
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        raise ValueError(f"{value} out of range {lo}–{hi}")
    return n


def clean_participants(rows: list[dict]) -> tuple[list[dict], int, list[str]]:
    """Returns (consented valid rows, number who declined data collection, problems found)."""
    kept, declined, problems = [], 0, []
    for i, r in enumerate(rows, start=2):  # line 1 is the header
        pid = r.get("participant_id") or f"line {i}"
        consent = r.get("consent_data", "").lower()
        if consent != "yes":
            if consent == "no":
                declined += 1
            else:
                problems.append(f"{pid}: consent_data must be yes or no; row ignored")
            continue
        try:
            row = {
                "id": pid,
                "finished": r.get("finished", "").lower(),
                "time": _num(r.get("time_minutes", ""), 0, 120),
                "turns": _num(r.get("turns", ""), 0, 50, integer=True),
                "decode": r.get("opened_decode", "").lower(),
                "usefulness": _num(r.get("usefulness", ""), 1, 5, integer=True),
                "realism": _num(r.get("realism", ""), 1, 5, integer=True),
                "retried": r.get("retried", "").lower(),
                "feedback": r.get("feedback", ""),
                "quote_ok": r.get("consent_quote", "").lower() == "yes",
                "issues": [x.strip() for x in r.get("observed_issues", "").split(";") if x.strip()],
                "experience": r.get("prior_experience", "").lower(),
            }
        except ValueError as exc:
            problems.append(f"{pid}: {exc}; row ignored")
            continue
        for field in ("finished", "decode", "retried"):
            if row[field] and row[field] not in YES_NO:
                problems.append(f"{pid}: {field} should be yes or no (got '{row[field]}')")
        kept.append(row)
    return kept, declined, problems


def _stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return "no data"
    if len(values) == 1:
        return f"{values[0]:g} (n=1)"
    return (f"mean {st.mean(values):.2f}, median {st.median(values):g}, range {min(values):g}–{max(values):g} "
            f"(n={len(values)})")


def _rate(rows, field):
    answered = [r for r in rows if r[field] in YES_NO]
    if not answered:
        return "no data"
    yes = sum(r[field] == "yes" for r in answered)
    return f"{yes} of {len(answered)}"


def summarize(participants: list[dict], ratings: list[dict]) -> str:
    rows, declined, problems = clean_participants(participants)
    out = ["# Evaluation results (real participants)\n",
           f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `scripts/summarize_evaluation.py` from "
           "`evaluation/participant_data.csv` and `evaluation/comparison_ratings.csv`. Only consented rows are counted.\n"]

    if not rows:
        out.append("**No participant data collected yet.** Nothing below is a finding.\n")
        if declined:
            out.append(f"{declined} participant(s) declined data collection (counted only, not recorded).\n")
    else:
        out.append(f"**Participants with consent:** {len(rows)}. **Declined data collection:** {declined}.\n")
        if len(rows) < 5:
            out.append("> With fewer than 5 participants, treat these as individual observations, not statistics.\n")
        finished = [r for r in rows if r["finished"] == "yes"]
        out.append("| Measure | Result |\n|---|---|")
        out.append(f"| Finished the simulation | {_rate(rows, 'finished')} |")
        out.append(f"| Time to finish (minutes, finished only) | {_stats([r['time'] for r in finished])} |")
        out.append(f"| Turns sent | {_stats([r['turns'] for r in rows])} |")
        out.append(f"| Usefulness (1–5) | {_stats([r['usefulness'] for r in rows])} |")
        out.append(f"| Realism (1–5) | {_stats([r['realism'] for r in rows])} |")
        out.append(f"| Retried without prompting | {_rate(rows, 'retried')} |")
        out.append(f"| Opened Decode this situation | {_rate(rows, 'decode')} |")
        for field, label in (("usefulness", "Usefulness"), ("realism", "Realism")):
            dist = Counter(r[field] for r in rows if r[field] is not None)
            if dist:
                out.append(f"\n{label} ratings: " + ", ".join(f"{k} × {dist[k]}" for k in range(1, 6) if dist[k]))

        out.append("\n## Participant feedback\n")
        quoted = [r for r in rows if r["feedback"] and r["quote_ok"]]
        withheld = sum(1 for r in rows if r["feedback"] and not r["quote_ok"])
        for r in quoted:
            out.append(f"- {r['id']}: \"{r['feedback']}\"")
        if withheld:
            out.append(f"- {withheld} more comment(s) recorded but not quoted (no quote consent).")
        if not quoted and not withheld:
            out.append("- None recorded.")

        out.append("\n## Observed confusion or failures\n")
        issues = Counter(i for r in rows for i in r["issues"])
        out.extend(f"- {issue} ({n} participant{'s' if n > 1 else ''})" for issue, n in issues.most_common()) if issues \
            else out.append("- None recorded.")

    out.append("\n## Comparison ratings (A / B / C)\n")
    valid = []
    for i, r in enumerate(ratings, start=2):
        if r.get("condition", "").upper() not in {"A", "B", "C"}:
            problems.append(f"comparison line {i}: condition must be A, B, or C; row ignored")
            continue
        try:
            valid.append({"condition": r["condition"].upper(),
                          **{c: _num(r.get(c, ""), 1, 5, integer=True)
                             for c in ("specificity", "realism", "actionability", "consistency")},
                          "time": _num(r.get("time_minutes", ""), 0, 120)})
        except ValueError as exc:
            problems.append(f"comparison line {i}: {exc}; row ignored")
    if not valid:
        out.append("**No human comparison ratings collected yet.** See `evaluation/internal_evaluation.md` for the "
                   "automated internal comparison, which is a separate, weaker kind of evidence.\n")
    else:
        out.append("| Condition | Specificity | Realism | Actionability | Consistency | Time (min) |\n|---|---|---|---|---|---|")
        for cond in ("A", "B", "C"):
            rs = [r for r in valid if r["condition"] == cond]
            if rs:
                cells = [_stats([r[c] for r in rs]) for c in ("specificity", "realism", "actionability", "consistency", "time")]
                out.append(f"| {cond} | " + " | ".join(cells) + " |")

    if problems:
        out.append("\n## Data problems found\n")
        out.extend(f"- {p}" for p in problems)
    return "\n".join(out) + "\n"


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--participants", default=str(EVAL_DIR / "participant_data.csv"))
    ap.add_argument("--ratings", default=str(EVAL_DIR / "comparison_ratings.csv"))
    ap.add_argument("--out", default=str(EVAL_DIR / "results_summary.md"))
    args = ap.parse_args()
    text = summarize(_read(Path(args.participants)), _read(Path(args.ratings)))
    Path(args.out).write_text(text)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main_cli()
