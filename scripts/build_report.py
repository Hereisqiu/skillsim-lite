"""Build report.html from the project's real logs and exports. Every number is computed here from files.

    python -m scripts.build_report [--repo-url URL]

Inputs: exports/measurements.json, exports/bench-*.json/_requests.csv, exports/security_evidence.json,
evaluation/internal_evaluation.json, evaluation/results_summary.md, data/sessions.json, data/requests.jsonl,
report_assets/*.jpg (screenshots of the running app). Runs the offline test suite to report its result.
"""

from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import re
import statistics as st
import subprocess
import sys
from datetime import datetime, timezone

from backend import config, ledger, store

ROOT = config.ROOT
ASSETS = ROOT / "report_assets"
TRACE_SESSION = "ef22e1abf81b"
CALIBRATION = ("6d77719942ca", "15f0757aac0d")
BENCH_A = "bench-20261024T021837Z"   # baseline vs optimized
BENCH_B = "bench-20261024T035739Z"   # optimized vs prefetch
ACCESSED = "October 24, 2026"

e = html.escape


def img(name: str, alt: str, caption: str, width: str = "100%") -> str:
    data = base64.b64encode((ASSETS / name).read_bytes()).decode()
    return (f'<figure style="width:{width}"><img src="data:image/jpeg;base64,{data}" alt="{e(alt)}">'
            f"<figcaption>{caption}</figcaption></figure>")


def usd(x, digits=5):
    return "n/a" if x is None else f"${x:,.{digits}f}"


def n(x, d=0):
    return f"{x:,.{d}f}"


def pct(a, b):
    return f"{100 * (b - a) / a:+.1f}%"


def bar_chart(rows, unit_fmt, title, max_value=None, width=620):
    """Single-series horizontal bars (one hue), value labels at the tip, 1px recessive axis."""
    max_value = max_value or max(v for _, v in rows) * 1.15
    label_w, bar_h, gap, top = 230, 18, 16, 8
    h = top + len(rows) * (bar_h + gap) + 4
    plot_w = width - label_w - 90
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img" aria-label="{e(title)}" class="chart">']
    out.append(f'<line x1="{label_w}" y1="{top - 4}" x2="{label_w}" y2="{h - 2}" stroke="#d9dcea" stroke-width="1"/>')
    for i, (label, value) in enumerate(rows):
        y = top + i * (bar_h + gap)
        w = max(2, plot_w * value / max_value)
        out.append(f'<text x="{label_w - 10}" y="{y + bar_h * 0.72}" text-anchor="end" class="ch-label">{e(label)}</text>')
        out.append(f'<path d="M{label_w},{y} h{w - 4} a4,4 0 0 1 4,4 v{bar_h - 8} a4,4 0 0 1 -4,4 h-{w - 4} z" fill="#3b5bdb">'
                   f"<title>{e(label)}: {e(unit_fmt(value))}</title></path>")
        out.append(f'<text x="{label_w + w + 8}" y="{y + bar_h * 0.72}" class="ch-value">{e(unit_fmt(value))}</text>')
    out.append("</svg>")
    return "".join(out)


ARCH_SVG = """
<svg viewBox="0 0 760 430" width="100%" role="img" aria-label="SkillSim architecture" class="arch">
 <defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
  <path d="M0,0 L10,5 L0,10 z" fill="#4d5679"/></marker></defs>
 <g font-family="Inter, -apple-system, Segoe UI, sans-serif" font-size="12" fill="#1a2142">
  <rect x="10" y="20" width="150" height="74" rx="10" fill="#f4f6ff" stroke="#c9d1fb"/>
  <text x="85" y="46" text-anchor="middle" font-weight="700">Browser</text>
  <text x="85" y="64" text-anchor="middle" font-size="11" fill="#4d5679">static HTML/CSS/JS</text>
  <text x="85" y="80" text-anchor="middle" font-size="11" fill="#4d5679">no keys, random client ID</text>

  <rect x="210" y="10" width="190" height="94" rx="10" fill="#1e2a5a"/>
  <text x="305" y="36" text-anchor="middle" font-weight="700" fill="#fff">FastAPI server</text>
  <text x="305" y="54" text-anchor="middle" font-size="11" fill="#c9d1fb">session ownership · limits</text>
  <text x="305" y="70" text-anchor="middle" font-size="11" fill="#c9d1fb">token budgets · timeout</text>
  <text x="305" y="86" text-anchor="middle" font-size="11" fill="#c9d1fb">orchestrates the agents</text>
  <line x1="160" y1="57" x2="206" y2="57" stroke="#4d5679" stroke-width="1.5" marker-end="url(#ar)"/>

  <rect x="450" y="10" width="300" height="94" rx="10" fill="#fff" stroke="#c9d1fb"/>
  <text x="600" y="34" text-anchor="middle" font-weight="700">ModelClient → Portkey → gpt-6-luna</text>
  <text x="600" y="54" text-anchor="middle" font-size="11" fill="#4d5679">Responses API · 45 s timeout · 2 retries (transient only)</text>
  <text x="600" y="70" text-anchor="middle" font-size="11" fill="#4d5679">per-request ledger: tokens, cost, latency, cache status</text>
  <text x="600" y="86" text-anchor="middle" font-size="11" fill="#4d5679">secrets redacted from every log</text>
  <line x1="400" y1="57" x2="446" y2="57" stroke="#4d5679" stroke-width="1.5" marker-end="url(#ar)"/>

  <g>
   <rect x="20" y="170" width="220" height="110" rx="10" fill="#f4f6ff" stroke="#8b9cf7"/>
   <text x="130" y="194" text-anchor="middle" font-weight="700">1 · DecodeAgent</text>
   <text x="130" y="213" text-anchor="middle" font-size="11" fill="#4d5679">before practice (optional)</text>
   <text x="130" y="231" text-anchor="middle" font-size="11" fill="#4d5679">sees only public scenario info</text>
   <text x="130" y="249" text-anchor="middle" font-size="11" fill="#4d5679">output: DecodeOut (JSON schema)</text>
   <text x="130" y="267" text-anchor="middle" font-size="11" fill="#4d5679">cached once per scenario</text>
  </g>
  <g>
   <rect x="270" y="170" width="220" height="110" rx="10" fill="#f4f6ff" stroke="#8b9cf7"/>
   <text x="380" y="194" text-anchor="middle" font-weight="700">2 · RoleplayAgent</text>
   <text x="380" y="213" text-anchor="middle" font-size="11" fill="#4d5679">plays the character, each turn</text>
   <text x="380" y="231" text-anchor="middle" font-size="11" fill="#4d5679">sees private motivations + history</text>
   <text x="380" y="249" text-anchor="middle" font-size="11" fill="#4d5679">output: plain dialogue, checked</text>
   <text x="380" y="267" text-anchor="middle" font-size="11" fill="#4d5679">≤2 tool rounds per turn</text>
  </g>
  <g>
   <rect x="520" y="170" width="220" height="110" rx="10" fill="#f4f6ff" stroke="#8b9cf7"/>
   <text x="630" y="194" text-anchor="middle" font-weight="700">3 · FeedbackAgent</text>
   <text x="630" y="213" text-anchor="middle" font-size="11" fill="#4d5679">after "End", full transcript</text>
   <text x="630" y="231" text-anchor="middle" font-size="11" fill="#4d5679">sees criteria, not motivations</text>
   <text x="630" y="249" text-anchor="middle" font-size="11" fill="#4d5679">output: FeedbackOut (JSON schema)</text>
   <text x="630" y="267" text-anchor="middle" font-size="11" fill="#4d5679">quotes verified by the server</text>
  </g>
  <line x1="305" y1="104" x2="130" y2="166" stroke="#4d5679" stroke-width="1.5" marker-end="url(#ar)"/>
  <line x1="305" y1="104" x2="380" y2="166" stroke="#4d5679" stroke-width="1.5" marker-end="url(#ar)"/>
  <line x1="305" y1="104" x2="630" y2="166" stroke="#4d5679" stroke-width="1.5" marker-end="url(#ar)"/>
  <line x1="490" y1="225" x2="516" y2="225" stroke="#3b5bdb" stroke-width="2" marker-end="url(#ar)"/>
  <text x="503" y="160" text-anchor="middle" font-size="10.5" fill="#3b5bdb">transcript</text>

  <g font-size="11">
   <rect x="20" y="320" width="220" height="62" rx="8" fill="#fff" stroke="#d9dcea"/>
   <text x="130" y="342" text-anchor="middle" font-family="ui-monospace, Menlo, monospace">lookup_workplace_knowledge(section)</text>
   <text x="130" y="362" text-anchor="middle" fill="#4d5679">reads knowledge_base.json (enum)</text>
   <rect x="270" y="320" width="220" height="62" rx="8" fill="#fff" stroke="#d9dcea"/>
   <text x="380" y="342" text-anchor="middle" font-family="ui-monospace, Menlo, monospace">get_scenario_facts(topic)</text>
   <text x="380" y="362" text-anchor="middle" fill="#4d5679">reads scenario "facts" (enum)</text>
   <rect x="520" y="320" width="220" height="62" rx="8" fill="#fff" stroke="#d9dcea"/>
   <text x="630" y="342" text-anchor="middle" font-family="ui-monospace, Menlo, monospace">get_workplace_guidance(topic)</text>
   <text x="630" y="362" text-anchor="middle" fill="#4d5679">reads guidance.json (enum)</text>
  </g>
  <line x1="130" y1="280" x2="130" y2="316" stroke="#8b9cf7" stroke-width="1.5" marker-end="url(#ar)"/>
  <line x1="380" y1="280" x2="380" y2="316" stroke="#8b9cf7" stroke-width="1.5" marker-end="url(#ar)"/>
  <line x1="630" y1="280" x2="630" y2="316" stroke="#8b9cf7" stroke-width="1.5" marker-end="url(#ar)"/>
  <text x="380" y="410" text-anchor="middle" font-size="11" fill="#4d5679">All tools are read-only, take one enumerated argument, and read data already loaded in memory. No tool takes a path or opens a file.</text>
 </g>
</svg>"""


def load():
    meas = json.loads((ROOT / "exports/measurements.json").read_text())
    bench_a = json.loads((ROOT / f"exports/{BENCH_A}.json").read_text())
    bench_b = json.loads((ROOT / f"exports/{BENCH_B}.json").read_text())
    rows_a = list(csv.DictReader(open(ROOT / f"exports/{BENCH_A}_requests.csv")))
    sec = json.loads((ROOT / "exports/security_evidence.json").read_text())
    ie = json.loads((ROOT / "evaluation/internal_evaluation.json").read_text())
    participants = [r for r in csv.DictReader(open(ROOT / "evaluation/participant_data.csv")) if r.get("consent_data") == "yes"]
    return meas, bench_a, bench_b, rows_a, sec, ie, participants


def run_tests():
    out = subprocess.run([sys.executable, "-m", "unittest"], cwd=ROOT, capture_output=True, text=True)
    text = out.stderr + out.stdout
    ran = re.search(r"Ran (\d+) tests", text)
    return int(ran.group(1)) if ran else 0, out.returncode == 0, text.strip().splitlines()[-1]


def first_request_tokens(rows):
    first = {}
    for r in sorted(rows, key=lambda r: float(r["ts"])):
        if not r["error"]:
            first.setdefault(r["session_id"], r)
    by = {}
    for r in first.values():
        by.setdefault((r["scenario_id"], r["variant"]), set()).add(int(r["input_tokens"]))
    return by


def _sec_outcome(r):
    if r["turns"] and "user" in r["turns"][0]:
        t = r["turns"][0]
        return (f"HTTP {t['status']}: {t['error']}" if t["status"] != 200 else f"In-character refusal: “{t['reply'][:110]}…”")
    return "; ".join(f"HTTP {t['status']}" + (f" ({t['model_requests']} model requests)" if "model_requests" in t else "") for t in r["turns"])


CSS = """
:root{--navy:#141c40;--navy2:#1e2a5a;--blue:#3b5bdb;--peri:#8b9cf7;--peri2:#c9d1fb;--peri3:#eef1ff;--ink:#1a2142;--soft:#4d5679;--mute:#7d85a6;--line:#e1e4f0;--amber:#fff4dd;--amberInk:#7a5000}
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);font-size:10pt;line-height:1.46;background:#fff}
.page{max-width:8.5in;margin:0 auto;padding:.6in .75in}
h1{font-size:30pt;line-height:1.1;margin:0 0 10px;color:var(--navy);letter-spacing:-.02em}
h2{font-size:17pt;color:var(--navy);margin:0 0 4px;letter-spacing:-.01em}
h2 .num{color:var(--blue);margin-right:8px}
h3{font-size:12pt;color:var(--navy2);margin:18px 0 6px}
p{margin:0 0 9px}
a{color:var(--blue);text-decoration:none}
.kicker{font-size:8.5pt;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--blue)}
.lede{font-size:12.5pt;color:var(--soft);margin:6px 0 18px}
.section{padding-top:4px}
.section-rule{height:3px;width:56px;background:var(--blue);border-radius:2px;margin:6px 0 14px}
.box{background:var(--peri3);border-left:3px solid var(--blue);padding:10px 14px;border-radius:0 8px 8px 0;margin:10px 0 12px}
.box.amber{background:var(--amber);border-left-color:#d79a00}
.box.navy{background:var(--navy2);color:#eef0ff;border:0;border-radius:8px}
.box.navy b{color:#fff}
.box p:last-child{margin:0}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:10px 0 12px}
.tile{border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.tile .v{font-size:15pt;font-weight:700;color:var(--navy)}
.tile .l{font-size:8pt;color:var(--mute);text-transform:uppercase;letter-spacing:.05em}
.tile .s{font-size:8pt;color:var(--soft)}
table{width:100%;border-collapse:collapse;font-size:8.7pt;margin:6px 0 10px}
th{text-align:left;font-size:7.6pt;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);border-bottom:1.5px solid var(--peri2);padding:4px 6px;background:var(--peri3)}
td{padding:3.5px 6px;border-bottom:1px solid var(--line);vertical-align:top}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr{break-inside:avoid}
figure{margin:8px auto 12px;break-inside:avoid}
figure img{width:100%;border:1px solid var(--line);border-radius:6px;display:block}
figcaption{font-size:8.3pt;color:var(--soft);margin-top:4px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}
.grid2 figure{margin:4px 0 8px}
.chart text.ch-label{font:9px Inter,-apple-system,sans-serif;fill:#1a2142}
.chart text.ch-value{font:9px Inter,-apple-system,sans-serif;fill:#4d5679}
.arch{margin:6px 0}
.tag{display:inline-block;font-size:7.5pt;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:1px 6px;border-radius:4px;background:#e3f6ec;color:#1f7a52}
.tag.plan{background:var(--amber);color:var(--amberInk)}
.tag.hyp{background:#eceefa;color:var(--soft)}
.todo{background:#fde8e8;color:#9b2c2c;padding:1px 6px;border-radius:4px;font-weight:600}
.t-line{display:grid;grid-template-columns:118px 1fr;gap:8px;font-size:8.8pt;padding:4px 0;border-bottom:1px dashed var(--line)}
.t-line span{font-weight:700;color:var(--soft);font-size:7.8pt;text-transform:uppercase;letter-spacing:.03em;padding-top:2px}
.t-line.you span{color:var(--blue)}
.cover{min-height:9.2in;display:flex;flex-direction:column}
.cover .brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:13pt;color:var(--navy);margin-bottom:60px}
.cover .mark{width:26px;height:26px;border-radius:7px;background:var(--navy2);position:relative}
.cover .mark:after{content:"";position:absolute;width:8px;height:8px;border-radius:50%;background:var(--peri);top:5px;right:5px}
.meta{display:grid;grid-template-columns:130px 1fr;gap:6px 14px;font-size:10pt;margin:20px 0}
.meta div:nth-child(odd){color:var(--mute);font-weight:600}
.toc{columns:2;font-size:10pt;margin-top:auto;border-top:1px solid var(--line);padding-top:14px}
.toc div{margin-bottom:4px}
.small{font-size:8.6pt;color:var(--soft)}
.refs li{margin-bottom:5px;font-size:8.8pt}
ul{margin:4px 0 10px;padding-left:18px}
li{margin-bottom:3px}
code{font-family:ui-monospace,Menlo,monospace;font-size:8.6pt;background:var(--peri3);padding:0 3px;border-radius:3px}
@page{size:letter;margin:.55in .6in .6in}
@media print{
 .page{padding:0;max-width:none}
 .break{break-before:page}
 .cover{min-height:9.6in}
 a{color:var(--blue)}
}
.next{margin-top:26px;padding-top:14px;border-top:1px solid var(--line)}
h2,h3{break-after:avoid}
.keep{break-inside:avoid}
.sec-head{break-after:avoid;break-inside:avoid}
.sec-head + p,.sec-head + .box,.sec-head + h3{break-before:avoid}
@media screen{.break{margin-top:40px;border-top:1px solid var(--line);padding-top:30px}}
"""

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SkillSim Lite · AI Foundations Final Project Report</title><style>{CSS}</style></head>
<body><main class="page">

<!-- 1. TITLE + LINKS -->
<section class="cover">
 <div class="brand"><span class="mark"></span>SkillSim</div>
 <div class="kicker">AI Foundations · Final Project Report</div>
 <h1>SkillSim Lite</h1>
 <p class="lede">SkillSim lets people rehearse hard workplace conversations with an AI character who has their own motives and pushes back. It first decodes the situation's unwritten expectations, then gives feedback grounded in exactly what the person said.</p>
 <div class="meta">
  <div>Author</div><div>Alice Liang</div>
  <div>GitHub</div><div>{repo_html}</div>
  <div>Application</div><div>Not deployed. Runs locally from the repository (<code>python run.py</code>, see README).</div>
  <div>Model</div><div><code>gpt-6-luna</code> via the course Portkey gateway</div>
  <div>Report built</div><div>{now}, from the app's logs and exports by <code>scripts/build_report.py</code></div>
 </div>
 <div class="box navy"><p><b>At a glance (all measured unless marked).</b> {S[runs]} fresh end-to-end simulations with the real model cost a mean of <b>{usd_mean}</b> each ({n_input} input tokens, {cache_pct}% of them served from the provider's prompt cache). The live security check passed <b>{sec[passed]} of {sec[total]}</b> attacks, and the offline test suite passed <b>{tests_ran}</b> tests. <b>No usability study with real participants has been run yet</b>; Section 7 says what that means for the impact claims.</p></div>
 <div class="toc">
  <div>1 · Title and links</div><div>2 · Motivation</div><div>3 · What is new</div><div>4 · The agents</div>
  <div>5 · Tokenomics</div><div>6 · Safety</div><div>7 · Impact</div><div>8 · Limitations and next steps</div><div>References</div>
 </div>
</section>

<!-- 2. MOTIVATION -->
<section class="section break">
 <div class="sec-head"><div class="kicker">Section 2</div><h2><span class="num">2</span>Motivation</h2><div class="section-rule"></div></div>
 <h3>Who has this problem</h3>
 <p>Some workplace conversations carry real stakes and follow rules nobody writes down: telling a direct report their work is slipping, countering a job offer, calming a client after your team made a mistake. People who grew up around professional offices pick these rules up informally. Many others don't, including:</p>
 <ul>
  <li><b>International students and early-career immigrants.</b> U.S. colleges hosted 1,177,766 international students in 2024/25, and 294,253 were on Optional Practical Training, working in U.S. jobs, often for the first time [2].</li>
  <li><b>First-generation professionals.</b> One workforce program starts from the observation that first-generation graduates "might not be aware of certain 'unwritten rules'" at work [3].</li>
  <li><b>New managers and anyone facing a first-of-its-kind conversation</b>, such as a first salary negotiation or a first escalation from an unhappy client.</li>
 </ul>
 <h3>Why it's hard if you're new to professional norms</h3>
 <p>The difficulty usually isn't vocabulary. It's interpretation and timing. "Let me see what I can do" may signal real flexibility or a polite close. "It's been a lot" can be an invitation to ask more. A manager's mention of the "performance review" can land as a threat even when it isn't meant as one. Power dynamics shape what the other person can say aloud: a direct report may not admit that a VP pulled them onto other work, and a recruiter won't reveal the top of a salary band. These meanings vary by workplace and culture, so there's rarely a single correct script.</p>
 <h3>Current workarounds</h3>
 <ul>
  <li><b>Reading generic advice</b> (articles, books, career-center handouts): accessible but not interactive, and silent about what <i>you</i> actually said.</li>
  <li><b>Practicing with a mentor or friend:</b> effective but scarce, socially costly to repeat, and dependent on who you happen to know.</li>
  <li><b>Paid coaching or corporate training platforms:</b> often strong, but usually bought by employers for specific roles such as sales (see Section 3).</li>
  <li><b>Asking a general chatbot to role-play:</b> instantly available, but the user has to supply the scenario, the other person's motives, and the evaluation criteria themselves.</li>
 </ul>
 <h3>Why it matters</h3>
 <p>Employers say they want these skills. In NACE's Job Outlook 2026 (Spring Update), as reported by Iowa State University, 78% of employers seek verbal communication skills and 72% written communication skills on a candidate's résumé [1]. A mishandled conversation has concrete costs: a negotiated salary that stays lower, a direct report who disengages, a client account at risk. The people least likely to have a mentor to rehearse with are often the ones navigating the least familiar norms. SkillSim's premise is that a low-cost, private, repeatable rehearsal could help close part of that gap. <span class="tag hyp">Hypothesis</span> That premise has not yet been tested with users (Section 7).</p>
</section>

<!-- 3. WHAT IS NEW -->
<section class="section next">
 <div class="sec-head"><div class="kicker">Section 3</div><h2><span class="num">3</span>What is new, and what isn't</h2><div class="section-rule"></div></div>
 <p><b>AI role-play for workplace conversations already exists, and several products do it well.</b> Each product page below was reviewed on {ACCESSED}. Capabilities are summarized from each vendor's own public description, which we did not independently test.</p>
 <table>
  <thead><tr><th style="width:15%">Product</th><th style="width:28%">Primary focus</th><th>What it offers (vendor's description)</th></tr></thead>
  <tbody>
   <tr><td><b>Yoodli</b> [4]</td><td>AI role-play coaching for sales and enablement teams, also managers and leaders</td><td>Role-play personas and scenarios with rubrics. Feedback on delivery (pacing, tone) and content. Lists use cases including "manager coaching" and "difficult conversations". Enterprise customization and integrations.</td></tr>
   <tr><td><b>Second Nature</b> [5]</td><td>Sales and support team training</td><td>Conversational AI "virtual pitch partner" with avatars and multi-persona meetings. Scoring, real-time feedback, manager analytics, custom scenarios, 30+ languages.</td></tr>
   <tr><td><b>Huru</b> [6]</td><td>Job-interview practice for individuals</td><td>Live AI interviewer that adapts follow-up questions. Scoring with per-answer criteria, delivery analysis, and "moments to rework", each with <b>an exact quote and a stronger alternative</b>. Free for individuals.</td></tr>
   <tr><td><b>ChatGPT</b> [7]</td><td>General-purpose assistant</td><td>Will role-play when asked, including by voice. Custom GPTs can carry instructions and files. The user designs the scenario and decides what good feedback looks like.</td></tr>
  </tbody>
 </table>
 <p>Two things SkillSim does are therefore <b>not</b> new. Practicing difficult conversations with an AI partner is offered by Yoodli and Second Nature. Feedback that quotes the user and proposes a better line is offered by Huru.</p>
 <h3>What SkillSim does differently</h3>
 <p>SkillSim's focus is narrower: <b>helping someone who doesn't know the unwritten expectations of a situation</b>, rather than training a sales team or rehearsing an interview. Within that focus, the design choices are these:</p>
 <ul>
  <li><b>Decode this situation, before practicing.</b> A separate agent explains likely meanings of workplace phrases ("band", "internal equity", "blocked", "in writing"), the power dynamics, what the user can't know yet, and questions they could ask. It is grounded in a small curated knowledge base, and the app labels it as "not universal, not externally verified." We did not find this step described on the product pages above. That is not proof that no product offers it.</li>
  <li><b>A character with private motivations and proportionate resistance.</b> Each scenario has hidden motives (for example, Jordan was pulled onto a VP's project and is embarrassed). The character reveals them only when the user's approach would realistically earn it, and looks up facts with a tool instead of inventing them.</li>
  <li><b>Feedback that is checked, not just generated.</b> The server rejects any "quote" that doesn't appear verbatim in the user's own messages, drops praise without a quote, removes comments on personal traits (personality, accent, gender, and similar), frames interpretations as possibilities, and presents its alternative as one valid style among several. Huru also quotes users. The difference is the server-side verification and the explicit rules about framing.</li>
  <li><b>Transparent cost and safety.</b> Every request is metered and inspectable in a developer trace, and the defenses are tested (Sections 5 and 6).</li>
 </ul>
 <div class="box amber"><p><b>What the others have that SkillSim doesn't:</b> voice and video, delivery metrics (pace, filler words), enterprise administration, many more scenarios, and real user bases. SkillSim is a three-scenario, text-only prototype.</p></div>
</section>

<!-- 4. AGENTS -->
<section class="section next">
 <div class="sec-head"><div class="kicker">Section 4</div><h2><span class="num">4</span>The agents</h2><div class="section-rule"></div></div>
 <p>SkillSim uses three AI agents with separate jobs, separate information, and separate permissions. The FastAPI server orchestrates them: no agent calls another directly. When the user clicks <i>End</i>, the server passes the full transcript from the conversation to the FeedbackAgent. When the user retries, the server copies the previous feedback's retry challenge into the new session and shows it to the <i>user</i>; it is not shown to the character.</p>
 {ARCH_SVG}
 <table>
  <thead><tr><th style="width:13%">Agent</th><th style="width:29%">Job and what it sees</th><th style="width:21%">Tool (read-only)</th><th style="width:37%">Output and checks</th></tr></thead>
  <tbody>
   <tr><td><b>DecodeAgent</b></td><td>Explains phrases, dynamics, unknowns, and questions before practice. Sees only what the user can see: no private motivations or facts.</td><td><code>lookup_workplace_knowledge(section)</code>: 5 sections of <code>knowledge_base.json</code></td><td>Strict JSON schema (<code>DecodeOut</code>), validated with Pydantic. Phrases not in the curated notes are removed. Cached once per scenario.</td></tr>
   <tr><td><b>RoleplayAgent</b></td><td>Plays the character, one reply per user turn. Sees the character's profile, private motivations, resistance rules, boundaries, and the conversation; never the user's objective or the scoring criteria.</td><td><code>get_scenario_facts(topic)</code>: that scenario's curated facts</td><td>Plain dialogue, at most 400 output tokens. The output guard rejects replies that leave character, repeat hidden instructions, contain secrets, claim legal or official authority, or state figures found nowhere in the scenario or the user's words. It regenerates once, then blocks.</td></tr>
   <tr><td><b>FeedbackAgent</b></td><td>Reviews the finished conversation as a separate reviewer. Sees the user's role, objective, criteria, and the transcript (marked as data, not instructions).</td><td><code>get_workplace_guidance(topic)</code>: curated <code>guidance.json</code> (it may call this; it isn't required to)</td><td>Strict JSON schema (<code>FeedbackOut</code>) with six parts plus a skill check, validated with Pydantic (one retry). Quotes are verified, trait comments removed, scores clamped to 1–5, and the overall score recomputed by the server.</td></tr>
  </tbody>
 </table>
 <p><b>Model.</b> All agents use <code>gpt-6-luna</code> through the course's Portkey gateway (Responses API), the only model the course key allows. It is inexpensive (${price[input]:.2f} input / ${price[output]:.2f} output per million tokens; see Section 5) and fast enough for conversation. Reasoning effort is set to <code>none</code> because each step is short and concrete. Instructions, scenario data, and user text always travel in separate message channels.</p>

 <h3>One real run, step by step</h3>
 <p>The following trace is session <code>{TRACE_SESSION}</code> ("Delivering tough feedback"), run in the browser on {trace_date} with the user's lines typed fresh. All {trows_len} model requests were new generations (Portkey cache status MISS). The app labels it "Attempt 2". An earlier attempt with the benchmark's exact wording was answered entirely from the gateway's response cache (Section 5), so it was set aside and is not shown.</p>
 <div class="grid2">
  {img_intro}
  {img_decode}
 </div>
 <p><b>Step 1: Select and decode.</b> The user reads the briefing, then opens <i>Decode this situation</i>. The DecodeAgent's output was generated once for this scenario (with real tool calls to the knowledge base) and is served from SkillSim's cache. That cached generation is the decode shown here.</p>
 <div class="grid2">
  {img_chat1}
  {img_chat2}
 </div>
 <p><b>Step 2: Conversation (RoleplayAgent).</b> Jordan is vague at first ("it's been a lot"). After the user's empathetic second question, Jordan reveals the hidden reason: rebrand work that Dana Ortiz (the VP of Marketing, per the scenario facts) asked for, about 12 hours a week, never in the sprint plan. Before stating those details, the agent made {n_tool} real tool calls: {tool_list}. The full transcript:</p>
 <div class="box">{transcript_html}</div>
 <p><b>Step 3: Feedback (FeedbackAgent).</b> After <i>End</i>, the server sent the transcript to the FeedbackAgent. Its JSON passed schema validation, and every quote shown was verified against the user's messages. Overall skill check: <b>{tfb[overall]}/100</b>. Retry challenge: <i>"{tfb_challenge}"</i></p>
 <div class="grid2">
  {img_fb1}
  {img_fb2}
 </div>
 <p><b>Step 4: What the server logged.</b> Each request, from the request ledger:</p>
 <table><thead><tr><th>#</th><th>Agent</th><th>Operation</th><th>Tool call requested</th><th class="num">Input</th><th class="num">Cached</th><th class="num">Output</th><th class="num">ms</th><th>Gateway</th></tr></thead>
 <tbody>{trace_rows}</tbody></table>
 <p class="small">Session totals: {n_t_in} input tokens ({n_t_cached} cached), {n_t_out} output tokens, {t_lat:.1f} s of model time, {usd_t_cost}.</p>
 {img_trace}
</section>

<!-- 5. TOKENOMICS -->
<section class="section next">
 <div class="sec-head"><div class="kicker">Section 5</div><h2><span class="num">5</span>Tokenomics</h2><div class="section-rule"></div></div>
 <p>Every model request is logged with the usage the API returned: input, cached input, and output tokens, plus latency, tool calls, errors, and Portkey's gateway cache status. Prices come from one file, <code>pricing.json</code>: ${price[input]:.2f} per million input tokens and ${price[output]:.2f} per million output tokens, from the course starter code (dated {price[as_of]}). <b>No cached-input rate is published, so cached tokens are billed at the full input rate. Every cost below is therefore an upper bound.</b></p>
 <div class="box amber"><p><b>A measurement trap we found.</b> The course gateway caches whole responses. Identical requests come back in a fraction of a second carrying the <i>original</i> token counts. Our first benchmark repeated identical scripts, and its later runs were mostly replays. We now log the cache status of every request, force fresh generations in benchmarks, and average only sessions in which every request was a fresh model call.</p></div>
 <h3>Measured: one full simulation (4 user turns + feedback)</h3>
 <div class="tiles">
  <div class="tile"><div class="l">Cost / simulation</div><div class="v">{usd_mean}</div><div class="s">median {usd_median} · p90 {usd_p90}</div></div>
  <div class="tile"><div class="l">Input tokens</div><div class="v">{n_input}</div><div class="s">{n_cached} cached ({cache_pct}%)</div></div>
  <div class="tile"><div class="l">Output tokens</div><div class="v">{n_output}</div><div class="s">mean per simulation</div></div>
  <div class="tile"><div class="l">Model requests</div><div class="v">{S[requests][mean]:.1f}</div><div class="s">per simulation (range {S[requests][min]}–{S[requests][max]})</div></div>
 </div>
 <p class="small">Source: <code>exports/measurements.json</code>. {S[runs]} fresh simulations: {variant_counts[baseline]} baseline, {variant_counts[optimized]} optimized (the current default; mean {usd_opt}), and {variant_counts[prefetch]} prefetch. All used 4 scripted or typed user turns across the three scenarios. The other {excluded} logged simulations are excluded because they contained gateway-cache replays or predate cache-status logging.</p>
 <h3>Where the tokens go</h3>
 {chart_shares}
 <p class="small">Share of input tokens by request type, across the {runs_a} runs of benchmark <code>{BENCH_A}</code>. About half of all input tokens are requests whose only output is a fact lookup. Each request resends the conversation, so the number of requests drives cost more than the size of any one request.</p>
 <table><thead><tr><th>Agent (all logged requests)</th><th class="num">Requests</th><th class="num">Input</th><th class="num">Cached input</th><th class="num">Output</th><th class="num">Cost</th></tr></thead><tbody>{agent_rows}</tbody></table>
 <p class="small">Totals cover every request logged during development, benchmarks, and evaluations ({n_all_req} successful requests, {usd_all_cost}). The {all_req[failed_requests]} failed attempts ({errors_text}) are logged and were retried or reported to the user; failed attempts return no token counts.</p>

 <h3>Projected cost at scale <span class="tag plan">Projection</span></h3>
 <table><thead><tr><th>Scenario</th><th class="num">Mean estimate</th><th class="num">High estimate (p90)</th></tr></thead><tbody>
  <tr><td>One user, one month</td><td class="num">{usd_pu}</td><td class="num">{usd_pu_hi}</td></tr>
  <tr><td>100 users, one month</td><td class="num">{usd_100}</td><td class="num">{usd_100_hi}</td></tr>
  <tr><td>10,000 users, one month</td><td class="num">{usd_10k}</td><td class="num">{usd_10k_hi}</td></tr>
 </tbody></table>
 <p class="small"><b>Assumptions:</b> {assumptions}</p>

 <h3>Cost optimizations and their measured effect</h3>
 <p><b>1. Compact context (adopted).</b> The same content is sent as compact JSON instead of indented JSON, repeat fact lookups are not re-sent, and a redundant topic list is removed. With identical inputs, the first request of every session shrank by {first_req_text}, identically on all three repetitions. Across whole sessions, though, the difference ({pct_a_in} input tokens, {pct_a_cost} cost) is smaller than the run-to-run variation, so <b>no session-level saving is claimed</b>.</p>
 <p><b>2. Prefetching facts (tested, not adopted).</b> Putting the character's facts in the cacheable prefix cut lookup requests per session from {lookups_opt} to {lookups_pre} and total requests by {pct_b_req}, but input tokens changed by only {pct_b_in} and cost by {pct_b_cost}, again within noise. It also gives the character every fact from the first turn, which risks earlier reveals.</p>
 <table><thead><tr><th>Variant</th><th class="num">Runs</th><th class="num">Requests</th><th class="num">Input</th><th class="num">Cached</th><th class="num">Output</th><th class="num">Cost</th><th class="num">Quality rubric</th></tr></thead><tbody>
  {opt_rows}
 </tbody></table>
 <p class="small"><b>Quality trade-off:</b> every variant scored 5/5 on our deterministic rubric (in character, figures consistent with the scenario, replies ≤ 90 words, no repetitive replies, feedback complete with no rejected quotes). The rubric showed no degradation. Because every run hit the ceiling, it also couldn't detect a small one. Sources: <code>exports/cost_optimization.md</code> and the two benchmark files.</p>
 <div class="grid2" style="width:80%;margin:0 auto">{img_dash}{img_proj}</div>
</section>

<!-- 6. SAFETY -->
<section class="section next">
 <div class="sec-head"><div class="kicker">Section 6</div><h2><span class="num">6</span>Safety</h2><div class="section-rule"></div></div>
 <div class="keep"><p>SkillSim handles private practice conversations, holds an API key, and lets anyone type anything to a model. The realistic risks, and what is <span class="tag">Implemented</span> (built and tested) versus <span class="tag plan">Planned</span> (not built):</p>
 <table><thead><tr><th style="width:21%">Risk</th><th>Defense</th><th style="width:13%">Status</th></tr></thead><tbody>
  <tr><td>Prompt injection in user text</td><td>Instructions, scenario data, and user text sent in separate channels; user text is never inserted into a prompt. Injection-like text is flagged in the trace. The provider's content filter is surfaced to the user.</td><td><span class="tag">Implemented</span></td></tr>
  <tr><td>Revealing hidden instructions or secrets</td><td>Keys live only on the server and are never sent to the model or the browser. Replies are checked for secrets and for repeated instruction text. Pasted keys are refused. Secrets are redacted from traces and logs.</td><td><span class="tag">Implemented</span></td></tr>
  <tr><td>Tool misuse for file access</td><td>Three allowlisted tools, one enumerated argument each, strict schemas. No tool takes a path or opens a file.</td><td><span class="tag">Implemented</span></td></tr>
  <tr><td>Runaway cost</td><td>1,200 characters per message, 12 turns per session, 1 message per second, 30-minute idle timeout, 80,000-token session budget with a check before each turn, daily token and dollar caps, 400-token replies, ≤2 tool rounds per turn, 2 retries on transient errors only, 45 s timeout.</td><td><span class="tag">Implemented</span></td></tr>
  <tr><td>Character leaves the role or fabricates authority</td><td>Output guard: "as an AI" breaks, legal or official authority claims, figures not in the scenario. Regenerate once, then block.</td><td><span class="tag">Implemented</span></td></tr>
  <tr><td>Feedback invents statements</td><td>Pydantic schema validation; quotes verified against the transcript; unquoted praise dropped; personal-trait comments removed.</td><td><span class="tag">Implemented</span></td></tr>
  <tr><td>Exposure of practice conversations</td><td>Sessions bound to a random per-browser ID (other browsers get 404); delete-my-history; developer views local-only; server binds to 127.0.0.1; the request log holds no conversation text.</td><td><span class="tag">Implemented</span></td></tr>
  <tr><td>Character agrees to a figure the user named</td><td>Not caught by the figure check. Relies on the character's prompt and boundaries.</td><td><span class="tag plan">Known gap</span></td></tr>
  <tr><td>Hosted deployment</td><td>Real accounts, encryption of stored transcripts, per-IP rate limits, and turning off developer views behind a proxy.</td><td><span class="tag plan">Planned</span></td></tr>
  <tr><td>Sensitive topics a user raises (harassment, crises)</td><td>No dedicated handling beyond the provider filter and the character's boundaries; no referral resources.</td><td><span class="tag plan">Planned</span></td></tr>
 </tbody></table></div>
 <h3>Test results</h3>
 <p><b>Offline suite:</b> {tests_ran} tests, result <code>{tests_line}</code> (run while building this report). The 28 security tests include a malicious prompt injection, an API-key extraction attempt, session and daily budget exhaustion, invalid structured output (fails safely; recovers on retry), and a normal successful run. <b>What testing found:</b> the first live budget test exposed a real defect. The budget was checked before each model call but not before each turn, so a turn could spend tokens and then fail. A check before each turn now refuses such turns with zero model calls. Separately, a check in our own evidence script had been written so it could never fail; it was corrected before the results below were produced.</p>
 <div class="keep"><p><b>Live attacks against the real model</b> (<code>exports/security_evidence.json</code>, {sec[passed]}/{sec[total]} passed):</p>
 <table><thead><tr><th style="width:28%">Attack</th><th style="width:20%">Threat</th><th style="width:8%">Result</th><th>What happened</th></tr></thead><tbody>{sec_rows}</tbody></table></div>
 <div class="grid2">{img_def1}{img_def2}</div>
</section>

<!-- 7. IMPACT -->
<section class="section next">
 <div class="sec-head"><div class="kicker">Section 7</div><h2><span class="num">7</span>Impact</h2><div class="section-rule"></div></div>
 <div class="box amber"><p><b>No real users have tested SkillSim yet.</b> The participant data file holds {n_participants} consented rows, so there are no usability ratings, completion times, testimonials, or learning outcomes to report. The study protocol (10–15 minutes per person, separate consent for data, quotes, and transcripts) and an analysis script are ready in <code>evaluation/</code>. Everything below is internal, automated evidence, which is weaker.</p></div>
 <h3>Internal comparison on the same scenario <span class="tag hyp">Automated proxies, no humans</span></h3>
 <p>Scenario: "Calming an upset client", identical scripted user turns, {ie[reps]} runs each. <b>A</b> = a page of generic advice. <b>B</b> = the same model as a plain chatbot (no system prompt, no scenario data, no tools), set up the way a user plausibly would. <b>C</b> = SkillSim. B and C use the same model, so differences come from SkillSim's design.</p>
 <table><thead><tr><th>Proxy (mean per run)</th><th class="num">A · advice</th><th class="num">B · chatbot</th><th class="num">C · SkillSim</th></tr></thead><tbody>{ie_rows}</tbody></table>
 <ul>
  <li><b>Specificity:</b> SkillSim's feedback quoted the user's own lines far more often (the quotes are required and verified). B's feedback did quote the user, but in shorter fragments; the post-hoc metric shows this and was added after we saw the data.</li>
  <li><b>Actionability:</b> both B and C gave a concrete alternative line. The "next step" proxy undervalues B, whose "what to improve" list was plausibly actionable.</li>
  <li><b>Consistency:</b> neither B nor C invented figures, so our hypothesis that SkillSim is more factually consistent was <b>not supported</b>.</li>
  <li><b>Time and cost:</b> SkillSim took about twice as long and cost about four times as much per run as the plain chatbot, because of fact lookups and structured feedback.</li>
 </ul>
 <h3>Feedback calibration check <span class="tag hyp">Internal, scripted</span></h3>
 <p>To see whether scores track quality, the author scripted a deliberately weak attempt at the upset-client scenario (technical jargon and blaming the client's test data; session <code>{cal[0][id]}</code>) and a strong one (ownership, a plan, dates; <code>{cal[1][id]}</code>). They scored <b>{cal0_score}</b> and <b>{cal1_score}</b>. This shows the scores move in the expected direction for an obvious contrast. It does not show that real users improve.</p>
 <h3>What the potential impact would look like <span class="tag hyp">Hypothesis</span></h3>
 <p>If the usability study confirms that people find the practice useful, the measured cost makes broad access plausible. At the mean measured cost, eight practice sessions per user per month comes to about {usd_pu} per user, and serving 10,000 users would cost roughly {usd_10k} per month in model fees (Section 5). A university career center or an ESL program could plausibly offer it to everyone, not only to people who can find a mentor. That depends on outcomes we haven't measured: whether users find the decode panel accurate, whether practice transfers to real conversations, and whether the feedback feels fair to people from different backgrounds.</p>
</section>

<!-- 8. LIMITATIONS -->
<section class="section next">
 <div class="sec-head"><div class="kicker">Section 8</div><h2><span class="num">8</span>Limitations and next steps</h2><div class="section-rule"></div></div>
 <h3>Technical limitations</h3>
 <ul>
  <li><b>Local prototype.</b> Not deployed; sessions are stored as unencrypted JSON on one machine; per-browser IDs are not accounts.</li>
  <li><b>Latency and cost.</b> About {lat_per_turn:.1f} s of model time per user turn in the traced run, and about four times the cost of a plain chatbot, mostly from fact-lookup requests (half of all input tokens).</li>
  <li><b>Guard limits.</b> The figure check can't catch a character agreeing to a number the user named. Regex-based checks can produce false positives or miss paraphrased leaks.</li>
  <li><b>Text only.</b> There is no voice or delivery feedback, which the established products in Section 3 do offer.</li>
 </ul>
 <h3>Uncertainty about feedback quality</h3>
 <p>The feedback is validated for <i>form</i> (schema, real quotes, no trait judgments), not for <i>truth</i>. Nobody has yet checked whether its interpretations are accurate or whether its scores agree with an experienced manager's judgment. Our quality rubric hit its ceiling on every run, so it couldn't detect small regressions. One model reviews another model's role-play, and both may share blind spots. The curated knowledge base reflects US-centric office norms written by one author.</p>
 <h3>Limited scenarios</h3>
 <p>Three scenarios (management feedback, salary negotiation, client recovery), each with fixed facts and one counterpart. Real situations involve more people, more history, and cultural context the scenarios don't capture.</p>
 <h3>Product-market fit hypotheses <span class="tag hyp">Untested</span></h3>
 <ul>
  <li>H1: International students on OPT and first-generation graduates will value <i>Decode this situation</i> more than general-purpose chatbot practice.</li>
  <li>H2: University career centers and English-language programs, not individuals, are the most likely buyers, because they already pay for interview-practice tools.</li>
  <li>H3: Users will retry a scenario when given a single, specific challenge rather than a long list of suggestions.</li>
 </ul>
 <h3>Next month, in order</h3>
 <ol>
  <li>Run the usability protocol with at least five participants from the target groups, and have a career advisor rate the A/B/C outputs blind.</li>
  <li>Calibrate feedback against human raters, and add a rubric that isn't capped by the ceiling problem.</li>
  <li>Let career-center staff author scenarios through a form, with review, so coverage grows beyond three.</li>
  <li>Deploy with accounts, encrypted storage, and retention controls; then consider voice.</li>
 </ol>
 <h3>The longer-term vision</h3>
 <p>A library of the conversations nobody teaches, written with people who have had them, and decoded honestly: <i>here is what this phrase usually means, here is what you can't know, here is a question you could ask</i>. Then a safe place to practice them until they feel familiar.</p>

 <h3>References</h3>
 <ol class="refs">
  <li>Iowa State University, College of Liberal Arts and Sciences Career Services, "What Employers Want," citing NACE <i>Job Outlook 2026, Spring Update</i>. careers.las.iastate.edu/career-resources/what-employers-want/ (accessed {ACCESSED}).</li>
  <li>Institute of International Education, "Open Doors 2025" press release. iie.org/news/open-doors-2025-press-release/ (accessed {ACCESSED}).</li>
  <li>OPB, "New Portland partnership aims to help BIPOC students and college graduates," Sept. 1, 2022. opb.org/article/2022/09/01/new-portland-partnership-aims-to-help-bipoc-students-and-college-graduates</li>
  <li>Yoodli, product home page. yoodli.ai (accessed {ACCESSED}).</li>
  <li>Second Nature, product home page. secondnature.ai (accessed {ACCESSED}).</li>
  <li>Huru, product home page. huru.ai (accessed {ACCESSED}).</li>
  <li>OpenAI Help Center, "ChatGPT capabilities overview" and "Voice Mode FAQ." help.openai.com (accessed {ACCESSED}).</li>
 </ol>
 <p class="small">Project evidence files (in the repository): <code>exports/measurements.json</code>, <code>exports/cost_optimization.md</code>, <code>exports/security_evidence.md</code>, <code>evaluation/internal_evaluation.md</code>, <code>evaluation/results_summary.md</code>, <code>pricing.json</code>.</p>
</section>
</main></body></html>
"""


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-url", default=None)
    args = ap.parse_args()
    html_text = render(args.repo_url)
    (ROOT / "report.html").write_text(html_text)
    print(f"Wrote report.html ({len(html_text) / 1e6:.2f} MB)")


def render(repo_url):
    meas, bench_a, bench_b, rows_a, sec, ie, participants = load()
    tests_ran, tests_ok, tests_line = run_tests()
    if not tests_ok:
        raise SystemExit(f"Tests failed ({tests_line}); fix before building the report.")
    M, P = meas["measured"], meas["projected"]
    S = M["simulation_summary"]
    fresh = [s for s in M["simulations"] if s["fresh"]]
    variant_counts = {v: sum(1 for s in fresh if s["variant"] == v) for v in ("baseline", "optimized", "prefetch")}
    opt_mean = st.mean(s["cost_usd"] for s in fresh if s["variant"] == "optimized")
    price = config.price_for("gpt-6-luna")
    all_req = M["all_requests"]
    errors = {}
    for r in ledger.read_all():
        if r.get("error"):
            errors[r["error"]] = errors.get(r["error"], 0) + 1
    errors_text = ", ".join(f"{v} {k}" for k, v in sorted(errors.items(), key=lambda kv: -kv[1]))

    ts = store.get(TRACE_SESSION)
    trows = [r for r in ledger.read_all() if r.get("session_id") == TRACE_SESSION]
    assert trows and all(r["gateway_cache"] in ("MISS", "REFRESH") for r in trows), "trace session must be fresh"
    tfb = ts["feedback"]
    t_lat = sum(r["latency_ms"] for r in trows) / 1000
    user_turns = sum(1 for m in ts["messages"] if m["role"] == "user")
    tool_calls = [ev["detail"] for ev in ts["trace"] if ev["event"] == "tool_call"]

    ok_a = [r for r in rows_a if not r["error"]]
    tot_a = sum(int(r["input_tokens"]) for r in ok_a)
    groups = [("Roleplay: lookup-only", [r for r in ok_a if r["agent"] == "roleplay" and r["tool_calls"]]),
              ("Roleplay: reply", [r for r in ok_a if r["agent"] == "roleplay" and not r["tool_calls"]]),
              ("Feedback", [r for r in ok_a if r["agent"] == "feedback"])]
    shares = [(name, 100 * sum(int(r["input_tokens"]) for r in g) / tot_a) for name, g in groups]
    first = first_request_tokens(ok_a)
    drops = []
    for sc in ("tough-feedback", "salary-negotiation", "upset-client"):
        b, o = first[(sc, "baseline")], first[(sc, "optimized")]
        assert len(b) == 1 and len(o) == 1, "first requests must be identical across reps"
        b, o = b.pop(), o.pop()
        drops.append((b - o, 100 * (b - o) / b))
    first_req_text = (f"{min(d for d, _ in drops)}–{max(d for d, _ in drops)} tokens "
                      f"({min(p for _, p in drops):.1f}–{max(p for _, p in drops):.1f}%)")

    ba, bb = bench_a["by_variant"], bench_b["by_variant"]
    cmp_b = bench_b["comparison"]["variants"]["prefetch"]
    lookups = {}
    rows_b = [r for r in csv.DictReader(open(ROOT / f"exports/{BENCH_B}_requests.csv")) if not r["error"]]
    for v in ("optimized", "prefetch"):
        sess = {r["session_id"] for r in rows_b if r["variant"] == v}
        lookups[v] = sum(1 for r in rows_b if r["variant"] == v and r["agent"] == "roleplay" and r["tool_calls"]) / len(sess)

    def opt_row(label, v):
        return (f"<tr><td>{label}</td><td class='num'>{v['runs']}</td><td class='num'>{v['requests']['mean']:.1f}</td>"
                f"<td class='num'>{n(v['input_tokens']['mean'])}</td><td class='num'>{n(v['cached_input_tokens']['mean'])}</td>"
                f"<td class='num'>{n(v['output_tokens']['mean'])}</td><td class='num'>{usd(v['cost_usd']['mean'])}</td>"
                f"<td class='num'>{v['quality_score']['mean']:.0f}/5</td></tr>")
    opt_rows = (opt_row(f"Baseline · run A", ba["baseline"]) + opt_row("Optimized · run A", ba["optimized"])
                + opt_row("Optimized · run B", bb["optimized"]) + opt_row("Prefetch · run B", bb["prefetch"]))

    agent_rows = "".join(
        f"<tr><td>{e(k)}</td><td class='num'>{v['requests']}</td><td class='num'>{n(v['input_tokens'])}</td>"
        f"<td class='num'>{n(v['cached_input_tokens'] or 0)}</td><td class='num'>{n(v['output_tokens'])}</td><td class='num'>{usd(v['cost_usd'], 4)}</td></tr>"
        for k, v in M["by_agent"].items())

    chart_shares = bar_chart(shares, lambda v: f"{v:.0f}% of input tokens", "Share of input tokens by request type", max_value=60)

    cal = [store.get(s) for s in CALIBRATION]
    ies = ie["summary"]
    ie_keys = [("user_lines_quoted (of 4)", "User lines quoted in feedback (of 4; ≥6 consecutive words)"),
               ("quoted_user_fragments (post-hoc)", "Quoted user fragments ≥3 words (post-hoc)"),
               ("alternative_line (share of runs)", "Concrete alternative line (share of runs)"),
               ("next_step (share of runs)", "Explicit next-step phrasing (share of runs)"),
               ("invented_figures", "Figures not in scenario or user's words"),
               ("model_seconds", "Model wait per run (seconds)"),
               ("reading_minutes_est", "Estimated reading time (minutes)"),
               ("cost_usd", "Model cost per run")]
    ie_rows = "".join("<tr><td>" + label + "</td>" + "".join(
        f"<td class='num'>{'—' if ies[c][k] is None else (('$0' if ies[c][k] == 0 else usd(ies[c][k])) if k == 'cost_usd' else ies[c][k])}</td>" for c in "ABC") + "</tr>"
        for k, label in ie_keys)

    sec_rows = "".join(f"<tr><td>{e(r['name'])}</td><td>{e(r['threat'])}</td><td>{'Pass' if r['passed'] else 'Fail'}</td>"
                       f"<td>{e(_sec_outcome(r))}</td></tr>" for r in sec["results"])

    transcript_html = "".join(
        f'<div class="t-line {"you" if m["role"] == "user" else "ai"}"><span>{"Manager (user)" if m["role"] == "user" else "Jordan (agent)"}</span>{e(m["text"])}</div>'
        for m in ts["messages"])
    trace_rows = "".join(
        f"<tr><td>{i}</td><td>{e(r['agent'])}</td><td>{e(r['operation'])}</td><td>{e(', '.join(r['tool_calls']) or 'none')}</td>"
        f"<td class='num'>{n(r['input_tokens'])}</td><td class='num'>{n(r['cached_input_tokens'] or 0)}</td><td class='num'>{n(r['output_tokens'])}</td>"
        f"<td class='num'>{n(r['latency_ms'])}</td><td>{e(r['gateway_cache'])}</td></tr>" for i, r in enumerate(trows, 1))

    repo_html = (f'<a href="{e(repo_url)}">{e(repo_url)}</a>' if repo_url else
                 '<span class="todo">Repository URL to be added before submission</span>')
    values = dict(
        CSS=CSS, ARCH_SVG=ARCH_SVG, ACCESSED=ACCESSED, BENCH_A=BENCH_A, TRACE_SESSION=TRACE_SESSION,
        now=datetime.now(timezone.utc).strftime("%B %d, %Y"), repo_html=repo_html, S=S, sec=sec, ie=ie,
        tests_ran=tests_ran, tests_line=e(tests_line), price=price, variant_counts=variant_counts,
        usd_mean=usd(S["cost_usd"]["mean"]), usd_median=usd(S["cost_usd"]["median"]), usd_p90=usd(S["cost_usd"]["p90"]),
        usd_opt=usd(opt_mean), n_input=n(S["input_tokens"]["mean"]), n_cached=n(S["cached_input_tokens"]["mean"]),
        n_output=n(S["output_tokens"]["mean"]), cache_pct=round(100 * S["cached_input_tokens"]["mean"] / S["input_tokens"]["mean"]),
        excluded=len(M["simulations"]) - len(fresh), runs_a=len(bench_a["simulations"]),
        chart_shares=chart_shares, agent_rows=agent_rows, all_req=all_req,
        n_all_req=n(all_req["requests"]), usd_all_cost=usd(all_req["cost_usd"], 4), errors_text=errors_text,
        usd_pu=usd(P["per_user_month"]["mean"], 4), usd_pu_hi=usd(P["per_user_month"]["high"], 4),
        usd_100=usd(P["users_100"]["mean"], 2), usd_100_hi=usd(P["users_100"]["high"], 2),
        usd_10k=usd(P["users_10000"]["mean"], 2), usd_10k_hi=usd(P["users_10000"]["high"], 2),
        assumptions=" ".join(e(a) for a in P["assumptions"]),
        first_req_text=first_req_text,
        pct_a_in=pct(ba["baseline"]["input_tokens"]["mean"], ba["optimized"]["input_tokens"]["mean"]),
        pct_a_cost=pct(ba["baseline"]["cost_usd"]["mean"], ba["optimized"]["cost_usd"]["mean"]),
        pct_b_req=f"{cmp_b['requests']['change_pct']:+.1f}%", pct_b_in=f"{cmp_b['input_tokens']['change_pct']:+.1f}%",
        pct_b_cost=f"{cmp_b['cost_usd']['change_pct']:+.1f}%",
        lookups_opt=f"{lookups['optimized']:.1f}", lookups_pre=f"{lookups['prefetch']:.1f}", opt_rows=opt_rows,
        trace_date=datetime.fromisoformat(ts["started_at"]).strftime("%B %d, %Y"), trows_len=len(trows),
        n_tool=len(tool_calls), tool_list=", ".join(f"<code>{e(t['tool'])}({e(t['args']['topic'])})</code>" for t in tool_calls),
        transcript_html=transcript_html, tfb=tfb, tfb_challenge=e(tfb["retry_challenge"]), trace_rows=trace_rows,
        n_t_in=n(sum(r["input_tokens"] for r in trows)), n_t_cached=n(sum(r["cached_input_tokens"] or 0 for r in trows)),
        n_t_out=n(sum(r["output_tokens"] for r in trows)), t_lat=t_lat, usd_t_cost=usd(sum(r["cost_usd"] for r in trows)),
        lat_per_turn=sum(r["latency_ms"] for r in trows if r["agent"] == "roleplay") / 1000 / user_turns,
        sec_rows=sec_rows, ie_rows=ie_rows, n_participants=len(participants),
        cal=cal, cal0_score=cal[0]["feedback"]["overall"], cal1_score=cal[1]["feedback"]["overall"],
        img_intro=img("03_intro.jpg", "Scenario briefing", "Scenario briefing: roles, relationship, power dynamics, objective."),
        img_decode=img("04_decode_phrases.jpg", "Decode panel", "Decode this situation: possible meanings, and what each depends on."),
        img_chat1=img("06_chat_reveal.jpg", "Chat start", "Turns 1–2: vague first, then the reveal after an empathetic question."),
        img_chat2=img("07_chat_end.jpg", "Chat end", "Turns 3–4: a shared plan, owner, and dates."),
        img_fb1=img("08_feedback_top.jpg", "Feedback top", "Feedback: what happened, what worked (verified quotes), one alternative."),
        img_fb2=img("09_feedback_detail.jpg", "Feedback detail", "Opportunity, an interpretation labeled as a possibility, skill check."),
        img_trace=img("11_trace.jpg", "Developer trace", "Developer trace for the same session: each model call, real tool call, and tool result.", "54%"),
        img_dash=img("12_dashboard.jpg", "Dashboard", "Developer dashboard: measured section (from the request ledger)."),
        img_proj=img("13_projection.jpg", "Projection", "The same dashboard's projection section, with its assumptions stated."),
        img_def1=img("defense_chat_injection_blocked.jpg", "Injection blocked",
                     "Real run: a polite request for hidden instructions gets an in-character refusal; a blunt injection is blocked and never added (turns stay 1/12)."),
        img_def2=img("defense_trace_guardrails.jpg", "Guardrail trace", "The server's trace for that session: injection flagged, provider filter refusal logged."),
    )
    return TEMPLATE.format(**values)


if __name__ == "__main__":
    main_cli()
