"""INTERNAL evaluation of conditions A / B / C on the same scenario. No human participants.

    python -m scripts.internal_evaluation [--reps 3]

A = generic written advice; B = the same model as a general chatbot (no system prompt, no scenario
data, no tools); C = SkillSim. B and C get identical scripted user turns. Every metric is an automatic
proxy defined in evaluation/comparison_framework.md. Real API calls (a few cents), gateway cache bypassed.
Writes evaluation/internal_evaluation.json and evaluation/internal_evaluation.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics as st
import time
from datetime import datetime, timezone

os.environ["SKILLSIM_GATEWAY_CACHE_REFRESH"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from backend import agents, config, ledger, main, store  # noqa: E402
from backend.llm import Budget  # noqa: E402
from backend.tools import GUIDANCE  # noqa: E402
from scripts.benchmark import SCRIPTS  # noqa: E402

SCENARIO_ID = "upset-client"
SCENARIO = main.SCENARIOS_BY_ID[SCENARIO_ID]
USER_TURNS = SCRIPTS[SCENARIO_ID]
EVAL_DIR = config.ROOT / "evaluation"
WPM = 200

# What a person would plausibly type into a general chatbot: the situation in their own words.
CHATBOT_SETUP = (
    "I'm an account manager at a software company. A bug in our integration with a client's scheduling system "
    "pushed their patient-portal launch back a week, after they'd already told about 3,000 patients it would go "
    "live Monday. Their Director of Operations, Marcus, is upset and calling me. Can you role-play Marcus so I can "
    "practice? Stay in character until I say 'end role-play'. Start with Marcus's first line."
)
CHATBOT_FEEDBACK = "End role-play. Give me feedback on how I handled it and what I should do differently next time."

DETAILS = ["3,000", "patients", "ceo", "thursday", "friday", "staging", "go/no-go", "front desk", "written summary",
           "wednesday", "scheduling", "renewal", "bayside", "marcus"]
STAGE_OR_PREFIX = re.compile(r"^\s*(\*\*?marcus\**:|marcus:)|\*[^*]+\*|\([^)]*\)|\[[^\]]*\]", re.I | re.M)
COACHING = re.compile(r"\b(tip|you could say|try saying|good job|well done|great job)\b", re.I)
PUSHBACK = re.compile(r"\?|\bbut\b|\bneed\b|\bwhy\b", re.I)
NEXT_STEP = re.compile(r"\b(next time|next attempt|on your next|for your next|next try)\b", re.I)
QUOTED = re.compile(r"[\"“]([^\"”]{20,})[\"”]")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'").replace("“", '"').replace("”", '"')).strip().lower()


def quotes_user(feedback: str, user_lines: list[str], n: int = 6) -> int:
    """User lines with at least n consecutive words appearing verbatim in the feedback."""
    fb, count = norm(feedback), 0
    for line in user_lines:
        words = norm(line).split()
        if any(" ".join(words[i:i + n]) in fb for i in range(len(words) - n + 1)):
            count += 1
    return count


def quoted_user_fragments(feedback: str, user_lines: list[str], n: int = 3) -> int:
    """POST-HOC (added after the first run): quoted fragments of >= n words copied from the user's lines."""
    users = " ".join(norm(u) for u in user_lines)
    frags = re.findall(r"[\"“]([^\"”]+)[\"”]", feedback)
    return sum(1 for f in frags if len(f.split()) >= n and norm(f).strip(" .,") in users)


def alternative_lines(text: str, user_lines: list[str]) -> list[str]:
    users = " ".join(norm(u) for u in user_lines)
    return [q for q in QUOTED.findall(text) if len(q.split()) >= 8 and norm(q) not in users]


def counterpart_metrics(replies: list[str], messages: list[dict]) -> dict:
    return {
        "replies": len(replies),
        "non_dialogue_replies": sum(bool(STAGE_OR_PREFIX.search(r) or agents.BROKE_CHARACTER.search(r) or COACHING.search(r))
                                    for r in replies),
        "max_reply_words": max((len(r.split()) for r in replies), default=0),
        "pushback_replies": sum(bool(PUSHBACK.search(r)) for r in replies),
        "invented_figures": sorted({f for r in replies for f in agents.invented_figures(r, SCENARIO, messages)}),
    }


def feedback_metrics(text: str, has_alternative: bool | None = None, has_next_step: bool | None = None) -> dict:
    words = len(text.split())
    return {
        "user_lines_quoted": quotes_user(text, USER_TURNS),
        "quoted_user_fragments_posthoc": quoted_user_fragments(text, USER_TURNS),
        "scenario_details_named": [d for d in DETAILS if d in text.lower()],
        "alternative_line": has_alternative if has_alternative is not None else bool(alternative_lines(text, USER_TURNS)),
        "next_step": has_next_step if has_next_step is not None else bool(NEXT_STEP.search(text)),
        "feedback_words": words,
        "reading_minutes_est": round(words / WPM, 2),
    }


def ledger_totals(predicate) -> dict:
    rows = [r for r in ledger.read_all() if predicate(r) and r.get("error") is None]
    return {"requests": len(rows), "input_tokens": sum(r["input_tokens"] for r in rows),
            "output_tokens": sum(r["output_tokens"] for r in rows),
            "cost_usd": round(sum(r["cost_usd"] or 0 for r in rows), 6),
            "model_seconds": round(sum(r["latency_ms"] for r in rows) / 1000, 1),
            "all_fresh": all(r.get("gateway_cache") in {"MISS", "REFRESH"} for r in rows)}


def run_a() -> dict:
    text = "\n\n".join(GUIDANCE[t]["title"] + "\n" + "\n".join("- " + p for p in GUIDANCE[t]["points"])
                       for t in SCENARIO["guidance_topics"])
    return {"condition": "A", "run_id": "A-static", "advice_text": text,
            "feedback": feedback_metrics(text), "counterpart": None,
            "time": {"model_seconds": 0, "reading_minutes_est": round(len(text.split()) / WPM, 2)}}


def run_b(rep: int, tag: str) -> dict:
    client = main.engine.client
    run_id = f"B-{tag}-{rep}"
    budget = Budget(0, client.prices, {"session_id": run_id, "scenario_id": SCENARIO_ID, "variant": "eval-chatbot", "run_tag": tag})
    convo, replies, trace = [{"role": "user", "content": CHATBOT_SETUP}], [], []

    def ask(operation):
        r, _, _ = client.create(agent="eval_chatbot", operation=operation, trace=trace, budget=budget,
                                input=convo, max_output_tokens=1500, reasoning={"effort": "none"})
        convo.append({"role": "assistant", "content": r.output_text})
        return r.output_text

    replies.append(ask("chatbot_turn"))
    for line in USER_TURNS:
        convo.append({"role": "user", "content": line})
        replies.append(ask("chatbot_turn"))
    convo.append({"role": "user", "content": CHATBOT_FEEDBACK})
    feedback = ask("chatbot_feedback")
    messages = [{"role": "user", "text": t} for t in USER_TURNS]
    totals = ledger_totals(lambda r: r.get("session_id") == run_id)
    return {"condition": "B", "run_id": run_id, "transcript": convo, "fresh": totals["all_fresh"],
            "counterpart": counterpart_metrics(replies[1:], messages), "opening": replies[0],
            "feedback": feedback_metrics(feedback), "feedback_text": feedback, "usage": totals,
            "time": {"model_seconds": totals["model_seconds"], "reading_minutes_est": round(len(feedback.split()) / WPM, 2)}}


def c_feedback_text(fb: dict) -> str:
    return " ".join([fb["what_happened"], *(f'{e["behavior"]} "{e["quote"]}"' for e in fb["effective"]),
                     fb["opportunity"]["description"], f'"{fb["opportunity"]["moment_quote"]}"',
                     fb["interpretation"]["possibility"], f'"{fb["alternative"]["response"]}"', fb["alternative"]["why"],
                     fb["retry_challenge"], *(k["note"] for k in fb["skills"])])


def run_c(api: TestClient, rep: int, tag: str) -> dict:
    sid = api.post("/api/sessions", json={"scenario_id": SCENARIO_ID}).json()["id"]
    session = store.get(sid)
    session["run_tag"] = tag
    store.put(session)
    for line in USER_TURNS:
        time.sleep(config.MIN_SECONDS_BETWEEN_MESSAGES)
        api.post(f"/api/sessions/{sid}/messages", json={"text": line}).raise_for_status()
    r = api.post(f"/api/sessions/{sid}/end")
    r.raise_for_status()
    s = r.json()
    fb = s["feedback"]
    fb_text = c_feedback_text(fb)
    replies = [m["text"] for m in s["messages"] if m["role"] == "ai" and m.get("source") == "live"]
    totals = ledger_totals(lambda row: row.get("session_id") == sid)
    return {"condition": "C", "run_id": f"C-{sid}", "session_id": sid, "fresh": totals["all_fresh"],
            "transcript": [{"role": m["role"], "text": m["text"]} for m in s["messages"]],
            "counterpart": counterpart_metrics(replies, s["messages"]),
            "feedback": feedback_metrics(fb_text, has_alternative=len(fb["alternative"]["response"].split()) >= 8,
                                         has_next_step=bool(fb["retry_challenge"])),
            "overall_score": fb["overall"], "feedback_json": fb, "usage": totals,
            "time": {"model_seconds": totals["model_seconds"], "reading_minutes_est": round(len(fb_text.split()) / WPM, 2)}}


def mean(values):
    values = [v for v in values if v is not None]
    return round(st.mean(values), 2) if values else None


def summarize(runs: list[dict]) -> dict:
    out = {}
    for cond in ("A", "B", "C"):
        rs = [r for r in runs if r["condition"] == cond]
        cp = [r["counterpart"] for r in rs if r["counterpart"]]
        scores = [r["overall_score"] for r in rs if "overall_score" in r]
        out[cond] = {
            "runs": len(rs),
            "user_lines_quoted (of 4)": mean([r["feedback"]["user_lines_quoted"] for r in rs]),
            "quoted_user_fragments (post-hoc)": mean([r["feedback"].get("quoted_user_fragments_posthoc") for r in rs]),
            "scenario_details_named": mean([len(r["feedback"]["scenario_details_named"]) for r in rs]),
            "alternative_line (share of runs)": mean([float(r["feedback"]["alternative_line"]) for r in rs]),
            "next_step (share of runs)": mean([float(r["feedback"]["next_step"]) for r in rs]),
            "non_dialogue_replies": mean([c["non_dialogue_replies"] for c in cp]) if cp else None,
            "max_reply_words": mean([c["max_reply_words"] for c in cp]) if cp else None,
            "pushback_replies (of 4)": mean([c["pushback_replies"] for c in cp]) if cp else None,
            "invented_figures": mean([len(c["invented_figures"]) for c in cp]) if cp else None,
            "overall_score_sd": round(st.stdev(scores), 2) if len(scores) > 1 else None,
            "overall_scores": scores or None,
            "model_seconds": mean([r["time"]["model_seconds"] for r in rs]),
            "reading_minutes_est": mean([r["time"]["reading_minutes_est"] for r in rs]),
            "cost_usd": (round(st.mean([r["usage"]["cost_usd"] for r in rs]), 5) if cond != "A" else 0),
        }
    return out


def hypothesis_checks(s: dict) -> list[str]:
    a, b, c = s["A"], s["B"], s["C"]
    lines = []
    lines.append(f"**H1 (C more specific than A and B):** C quoted {c['user_lines_quoted (of 4)']} of 4 user lines on average, "
                 f"B {b['user_lines_quoted (of 4)']}, A {a['user_lines_quoted (of 4)']}; scenario details named: "
                 f"C {c['scenario_details_named']}, B {b['scenario_details_named']}, A {a['scenario_details_named']}; "
                 f"post-hoc quoted fragments: C {c['quoted_user_fragments (post-hoc)']}, B {b['quoted_user_fragments (post-hoc)']}. "
                 + ("Consistent with H1 on these proxies." if c['user_lines_quoted (of 4)'] > max(b['user_lines_quoted (of 4)'], a['user_lines_quoted (of 4)'])
                    else "Not supported on the quoting proxy."))
    lines.append(f"**H2 (C more consistent on facts than B):** invented figures per run: C {c['invented_figures']}, B {b['invented_figures']}. "
                 + ("Consistent with H2." if (c['invented_figures'] or 0) < (b['invented_figures'] or 0)
                    else "Not supported: no difference on this proxy." if c['invented_figures'] == b['invented_figures']
                    else "Contradicts H2 on this proxy."))
    lines.append(f"**H3 (B at least as fast as C):** model wait per run: B {b['model_seconds']} s, C {c['model_seconds']} s; "
                 f"estimated reading: A {a['reading_minutes_est']}, B {b['reading_minutes_est']}, C {c['reading_minutes_est']} min. "
                 + ("Consistent with H3." if (b['model_seconds'] or 0) <= (c['model_seconds'] or 0) else "Not supported: B took longer."))
    lines.append(f"**H4 (similar realism for B and C):** non-dialogue replies B {b['non_dialogue_replies']}, C {c['non_dialogue_replies']}; "
                 f"longest reply B {b['max_reply_words']} words, C {c['max_reply_words']}; pushback replies B {b['pushback_replies (of 4)']}, "
                 f"C {c['pushback_replies (of 4)']}. Proxies only; realism needs human ratings.")
    lines.append("**H5 (users find C more useful than A):** not testable without participants.")
    return lines


def write_markdown(result: dict) -> str:
    s = result["summary"]
    rows = [k for k in s["C"] if k not in ("runs",)]
    md = ["# Internal evaluation: A vs B vs C (no human participants)\n",
          "> **This is not user testing.** No people took part. Every number is an automatic proxy computed from real model "
          "outputs on repeatable, scripted test cases, as defined in `comparison_framework.md`. These numbers are not opinions, "
          "ratings, or testimonials. Participant results, once collected, go in `results_summary.md`.\n",
          f"Run {result['generated_at']} · model {result['model']} · scenario *{SCENARIO['title']}* · "
          f"{result['reps']} runs each for B and C with identical scripted user turns · gateway cache bypassed · "
          f"all B/C runs fresh: {result['all_fresh']}\n",
          "## Results (mean per run)\n", "| Proxy | A: generic advice | B: general chatbot | C: SkillSim |", "|---|---|---|---|"]
    for k in rows:
        md.append(f"| {k} | " + " | ".join("—" if s[c][k] is None else str(s[c][k]) for c in "ABC") + " |")
    md.append("\n## Hypotheses vs. these internal results\n")
    md.extend(f"- {line}" for line in result["hypotheses"])
    md.append("\n## What these proxies cannot tell you\n")
    md.append("- Whether the feedback actually helps someone do better in a real conversation.")
    md.append("- Realism as a person feels it. The proxies only check form (dialogue, length, presence of pushback).")
    md.append("- Condition A involves no practice, so its realism and consistency don't apply.")
    md.append("- B's result depends on how the person phrases the request. The internal run uses one plausible phrasing (`CHATBOT_SETUP`).")
    md.append("- `user_lines_quoted` (defined before the run) needs 6 consecutive words. B tends to quote shorter fragments, so it "
              "undercounts B. `quoted_user_fragments (post-hoc)` was added *after* seeing the first results (quoted fragments of 3 or more "
              "words copied from the user) and is reported alongside it, not in place of it.")
    md.append("- `next_step` looks for phrases like \"next time\". B's feedback has a \"What to improve\" list that is plausibly actionable "
              "but doesn't use those phrases, so this proxy likely undervalues B. C scores 1.0 because its schema always includes a retry challenge.")
    md.append("- B's `scenario_details_named` is high partly because the user's own setup message supplied those details.")
    md.append("\n## Scripted user turns (identical for B and C)\n")
    md.extend(f"{i}. {t}" for i, t in enumerate(USER_TURNS, 1))
    md.append("\nFull transcripts and feedback for every run are in `internal_evaluation.json`.")
    return "\n".join(md) + "\n"


def recompute(path):
    """Recompute every proxy from a saved run file, with no API calls."""
    result = json.loads(open(path).read())
    for r in result["runs"]:
        if r["condition"] == "A":
            r["feedback"] = feedback_metrics(r["advice_text"])
        elif r["condition"] == "B":
            r["feedback"] = feedback_metrics(r["feedback_text"])
        else:
            fb = r["feedback_json"]
            r["feedback"] = feedback_metrics(c_feedback_text(fb), has_alternative=len(fb["alternative"]["response"].split()) >= 8,
                                             has_next_step=bool(fb["retry_challenge"]))
    result["summary"] = summarize(result["runs"])
    result["hypotheses"] = hypothesis_checks(result["summary"])
    result["recomputed_at"] = datetime.now(timezone.utc).isoformat()
    (EVAL_DIR / "internal_evaluation.json").write_text(json.dumps(result, indent=2))
    (EVAL_DIR / "internal_evaluation.md").write_text(write_markdown(result))
    print("Recomputed evaluation/internal_evaluation.json and .md from saved runs (no API calls)")


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--from-json", help="recompute proxies from a saved internal_evaluation.json")
    args = ap.parse_args()
    if args.from_json:
        return recompute(args.from_json)
    if main.engine is None or main.engine.source != "live":
        raise SystemExit(f"The live model isn't configured: {main.engine_error}")
    tag = "eval-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    api = TestClient(main.app, headers={"X-SkillSim-Client": f"internal-{tag}"})
    runs = [run_a()]
    for rep in range(1, args.reps + 1):
        for fn in ((lambda: run_b(rep, tag)), (lambda: run_c(api, rep, tag))):
            t0 = time.time()
            r = fn()
            runs.append(r)
            print(f"rep {rep} {r['condition']} {r['run_id']} {time.time() - t0:5.1f}s fresh={r.get('fresh')}", flush=True)
    summary = summarize(runs)
    result = {"label": "INTERNAL EVALUATION: automated proxies on scripted test cases; no human participants",
              "generated_at": datetime.now(timezone.utc).isoformat(), "run_tag": tag, "model": main.engine.model,
              "reps": args.reps, "all_fresh": all(r.get("fresh", True) for r in runs),
              "chatbot_prompts": {"setup": CHATBOT_SETUP, "feedback_request": CHATBOT_FEEDBACK}, "user_turns": USER_TURNS,
              "summary": summary, "hypotheses": hypothesis_checks(summary), "runs": runs}
    EVAL_DIR.mkdir(exist_ok=True)
    (EVAL_DIR / "internal_evaluation.json").write_text(json.dumps(result, indent=2))
    (EVAL_DIR / "internal_evaluation.md").write_text(write_markdown(result))
    print("Wrote evaluation/internal_evaluation.json and .md")


if __name__ == "__main__":
    main_cli()
