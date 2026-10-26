"""Build slides.html (reveal.js) from the same logs and exports as the report.

    python -m scripts.build_slides

Every number is computed from project files. Screenshots are embedded as data URIs.
reveal.js 5.1.0 is loaded from the jsDelivr CDN (as the assignment specifies). If the CDN can't be
reached, a small built-in fallback still shows one slide at a time with arrow keys and F for full screen.
"""

from __future__ import annotations

import base64
import html
import json
import re
import subprocess
import sys

from backend import config, store
from scripts.build_report import BENCH_A, CALIBRATION, ROOT, load

ASSETS = ROOT / "report_assets"
REVEAL = "https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist"
e = html.escape


def shot(name, alt, caption="", cls=""):
    data = base64.b64encode((ASSETS / name).read_bytes()).decode()
    cap = f"<figcaption>{caption}</figcaption>" if caption else ""
    return f'<figure class="{cls}"><img src="data:image/jpeg;base64,{data}" alt="{e(alt)}">{cap}</figure>'


def usd(x, d=5):
    return f"${x:,.{d}f}"


def build():
    meas, bench_a, bench_b, rows_a, sec, ie, participants = load()
    tests = subprocess.run([sys.executable, "-m", "unittest"], cwd=ROOT, capture_output=True, text=True)
    out = tests.stderr + tests.stdout
    if tests.returncode != 0:
        raise SystemExit("Tests failed; fix before building slides.")
    tests_ran = int(re.search(r"Ran (\d+) tests", out).group(1))

    M, P = meas["measured"], meas["projected"]
    S = M["simulation_summary"]
    ok_a = [r for r in rows_a if not r["error"]]
    tot_a = sum(int(r["input_tokens"]) for r in ok_a)
    lookup_share = 100 * sum(int(r["input_tokens"]) for r in ok_a if r["agent"] == "roleplay" and r["tool_calls"]) / tot_a
    ies = ie["summary"]
    cal = [store.get(s)["feedback"]["overall"] for s in CALIBRATION]
    budget = next(r for r in sec["results"] if r["threat"].startswith("4. Runaway") and "budget" in r["name"].lower())
    price = config.price_for("gpt-6-luna")

    # first-request saving from the controlled comparison (same as the report)
    first = {}
    for r in sorted(ok_a, key=lambda r: float(r["ts"])):
        first.setdefault(r["session_id"], r)
    by = {}
    for r in first.values():
        by.setdefault((r["scenario_id"], r["variant"]), set()).add(int(r["input_tokens"]))
    drops = [100 * (min(by[(sc, "baseline")]) - min(by[(sc, "optimized")])) / min(by[(sc, "baseline")])
             for sc in ("tough-feedback", "salary-negotiation", "upset-client")]

    v = dict(
        REVEAL=REVEAL, CSS=CSS, FALLBACK=FALLBACK, ARCH=ARCH,
        cost=usd(S["cost_usd"]["mean"]), runs=S["runs"], n_in=f"{S['input_tokens']['mean']:,.0f}",
        cache_pct=round(100 * S["cached_input_tokens"]["mean"] / S["input_tokens"]["mean"]),
        n_out=f"{S['output_tokens']['mean']:,.0f}", reqs=f"{S['requests']['mean']:.1f}",
        pu=usd(P["per_user_month"]["mean"], 4), u100=usd(P["users_100"]["mean"], 2), u10k=usd(P["users_10000"]["mean"], 2),
        u10k_hi=usd(P["users_10000"]["high"], 2), spm=f"{P['sessions_per_user_month']:g}",
        lookup_share=round(lookup_share), drop_lo=f"{min(drops):.1f}", drop_hi=f"{max(drops):.1f}",
        price_in=f"{price['input']:.2f}", price_out=f"{price['output']:.2f}",
        sec_pass=sec["passed"], sec_total=sec["total"], tests_ran=tests_ran,
        refused_calls=budget["turns"][-1]["model_requests"],
        q_c=ies["C"]["user_lines_quoted (of 4)"], q_b=ies["B"]["user_lines_quoted (of 4)"],
        t_b=ies["B"]["model_seconds"], t_c=ies["C"]["model_seconds"],
        c_b=usd(ies["B"]["cost_usd"]), c_c=usd(ies["C"]["cost_usd"]),
        speed_x=f"{ies['C']['model_seconds'] / ies['B']['model_seconds']:.1f}", cost_x=f"{ies['C']['cost_usd'] / ies['B']['cost_usd']:.1f}",
        inv_b=ies["B"]["invented_figures"], inv_c=ies["C"]["invented_figures"], reps=ie["reps"],
        cal_weak=cal[0], cal_strong=cal[1], n_participants=len(participants),
        img_landing=shot("01_landing.jpg", "SkillSim landing page", cls="hero-shot"),
        img_scen=shot("02_scenarios.jpg", "Scenario selection", "1 · Choose a scenario"),
        img_decode=shot("04_decode_phrases.jpg", "Decode this situation", "2 · Decode the situation"),
        img_chat=shot("06_chat_reveal.jpg", "Simulation", "3 · Rehearse with the character"),
        img_fb=shot("08_feedback_top.jpg", "Feedback", "4 · Feedback grounded in your words"),
        img_defense=shot("defense_chat_injection_blocked.jpg", "Injection blocked", "Real run: in-character refusal, then a blocked injection."),
    )
    return TEMPLATE.format(**v)


CSS = """
:root{--navy:#141c40;--navy2:#1e2a5a;--blue:#3b5bdb;--peri:#8b9cf7;--peri2:#c9d1fb;--peri3:#eef1ff;--ink:#1a2142;--soft:#4d5679;--mute:#7d85a6;--amber:#fff4dd;--amberInk:#7a5000}
.reveal{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);font-size:30px}
.reveal .slides{text-align:left}
.reveal .slides section{height:100%;padding:8px 6px;box-sizing:border-box}
.reveal h1,.reveal h2,.reveal h3{font-family:inherit;color:var(--navy);text-transform:none;letter-spacing:-.02em;margin:0 0 18px}
.reveal h1{font-size:76px;line-height:1.05}
.reveal h2{font-size:50px;line-height:1.1}
.reveal h3{font-size:30px;color:var(--navy2);margin-bottom:10px}
.reveal p,.reveal li{line-height:1.38}
.reveal ul{margin:0 0 0 1em}
.reveal li{margin-bottom:10px}
.kicker{font-size:18px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--blue);margin-bottom:10px}
.lede{font-size:34px;color:var(--soft);margin:0 0 26px}
.small{font-size:19px;color:var(--soft)}
.src{position:absolute;bottom:4px;left:6px;right:6px;font-size:15px;color:var(--mute)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:36px;align-items:start}
.cols.w60{grid-template-columns:1.25fr 1fr}
.card{background:#fff;border:2px solid var(--peri3);border-radius:16px;padding:18px 22px}
.big{font-size:64px;font-weight:800;color:var(--navy);line-height:1}
.big-l{font-size:19px;color:var(--soft);margin-top:6px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:8px 0 20px}
.stats.three{grid-template-columns:repeat(3,1fr)}
.stat{background:var(--peri3);border-radius:14px;padding:16px 18px}
.stat .n{font-size:44px;font-weight:800;color:var(--navy);line-height:1.05}
.stat .l{font-size:17px;color:var(--soft);margin-top:6px}
.proj .stat{background:var(--amber)}
.tag{display:inline-block;font-size:15px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;padding:4px 10px;border-radius:6px;vertical-align:middle}
.tag.m{background:#e3f6ec;color:#1f7a52}.tag.p{background:var(--amber);color:var(--amberInk)}.tag.h{background:#eceefa;color:var(--soft)}
.flow{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:16px 0 26px}
.step{background:var(--peri3);border-radius:16px;padding:20px 18px;position:relative}
.step .num{width:48px;height:48px;border-radius:12px;background:var(--navy2);color:#fff;font-weight:800;font-size:24px;display:grid;place-items:center;margin-bottom:12px}
.step b{display:block;font-size:30px;color:var(--navy);margin-bottom:6px}
.step span{font-size:19px;color:var(--soft);line-height:1.35;display:block}
.phrase{background:var(--peri3);border-left:6px solid var(--blue);border-radius:0 12px 12px 0;padding:12px 18px;margin-bottom:14px}
.phrase b{font-size:28px;color:var(--navy)}
.phrase span{display:block;font-size:20px;color:var(--soft)}
.reveal figure{margin:0}
.reveal figure img{width:100%;border:2px solid var(--peri3);border-radius:12px;margin:0;box-shadow:0 8px 28px rgba(20,28,64,.10)}
.reveal figcaption{font-size:17px;color:var(--soft);margin-top:6px}
.grid4{display:grid;grid-template-columns:1fr 1fr;gap:14px 22px}
.grid4 figure img{max-height:238px;object-fit:cover;object-position:top}
.title-slide .hero-shot{background:var(--peri3);border-radius:24px;padding:28px}
.brand{display:flex;align-items:center;gap:14px;font-weight:800;font-size:30px;color:var(--navy);margin-bottom:56px}
.mark{width:40px;height:40px;border-radius:10px;background:var(--navy2);position:relative;display:inline-block}
.mark:after{content:"";position:absolute;width:13px;height:13px;border-radius:50%;background:var(--peri);top:7px;right:7px}
.hero-shot img{transform:perspective(1200px) rotateY(-6deg)}
.note{background:var(--amber);border-radius:14px;padding:14px 20px;font-size:21px;color:#4a3400}
.honest{border-left:6px solid #d79a00;padding:6px 0 6px 18px;font-size:22px;color:var(--soft)}
table.mini{border-collapse:collapse;width:100%;font-size:20px}
table.mini td,table.mini th{padding:8px 10px;border-bottom:1px solid var(--peri3);text-align:left}
table.mini th{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute)}
table.mini td.r,table.mini th.r{text-align:right}
.arch text{font-family:Inter,-apple-system,sans-serif}
.reveal .slide-number{background:transparent;color:var(--mute);font-size:16px}
.reveal .progress{color:var(--blue)}
.reveal .controls{color:var(--blue)}
/* Fallback (CDN unreachable): one slide at a time, scaled to the window */
html.no-reveal,html.no-reveal body{margin:0;height:100%;background:#fff;overflow:hidden}
html.no-reveal .reveal{position:fixed;inset:0}
html.no-reveal .slides{position:absolute;left:50%;top:50%;width:1280px;height:720px;transform-origin:center center}
html.no-reveal .slides>section{display:none;position:absolute;inset:0;padding:40px 52px;box-sizing:border-box}
html.no-reveal .slides>section.present{display:block}
html.no-reveal .fallback-bar{position:fixed;bottom:8px;right:14px;font:14px Inter,sans-serif;color:#7d85a6}
"""

FALLBACK = """
<script>
// Fallback if reveal.js can't load from the CDN: one slide at a time, arrow keys / space to move, F for full screen.
window.addEventListener('load', function () {
  if (window.Reveal) {
    Reveal.initialize({hash:true, slideNumber:'c/t', width:1280, height:720, margin:0.04, center:false, transition:'fade', controls:true, progress:true});
    return;
  }
  document.documentElement.classList.add('no-reveal');
  var slides = Array.prototype.slice.call(document.querySelectorAll('.slides > section'));
  var i = Math.max(0, Math.min(slides.length - 1, (parseInt((location.hash.match(/\\d+/) || ['1'])[0], 10) || 1) - 1));
  var bar = document.createElement('div'); bar.className = 'fallback-bar'; document.body.appendChild(bar);
  function fit() { var s = Math.min(innerWidth / 1280, innerHeight / 720) * 0.96; document.querySelector('.slides').style.transform = 'translate(-50%, -50%) scale(' + s + ')'; }
  function show(n) { i = Math.max(0, Math.min(slides.length - 1, n)); slides.forEach(function (s, k) { s.classList.toggle('present', k === i); });
    bar.textContent = (i + 1) + ' / ' + slides.length + '  ·  offline mode (reveal.js CDN unavailable)'; history.replaceState(null, '', '#/' + (i + 1)); }
  document.addEventListener('keydown', function (ev) {
    if (['ArrowRight','ArrowDown','PageDown',' ','n'].indexOf(ev.key) >= 0) { show(i + 1); ev.preventDefault(); }
    else if (['ArrowLeft','ArrowUp','PageUp','p'].indexOf(ev.key) >= 0) { show(i - 1); ev.preventDefault(); }
    else if (ev.key === 'Home') show(0); else if (ev.key === 'End') show(slides.length - 1);
    else if (ev.key === 'f' || ev.key === 'F') { if (!document.fullscreenElement) document.documentElement.requestFullscreen(); else document.exitFullscreen(); }
  });
  addEventListener('resize', fit); fit(); show(i);
});
</script>"""

ARCH = """
<svg viewBox="0 0 1180 470" width="100%" class="arch" role="img" aria-label="SkillSim agent architecture">
 <defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="#4d5679"/></marker></defs>
 <rect x="20" y="20" width="230" height="96" rx="16" fill="#eef1ff"/><text x="135" y="62" text-anchor="middle" font-size="26" font-weight="800" fill="#141c40">Browser</text><text x="135" y="92" text-anchor="middle" font-size="18" fill="#4d5679">no keys · private ID</text>
 <rect x="440" y="10" width="300" height="116" rx="16" fill="#1e2a5a"/><text x="590" y="58" text-anchor="middle" font-size="26" font-weight="800" fill="#fff">FastAPI server</text><text x="590" y="88" text-anchor="middle" font-size="18" fill="#c9d1fb">limits · budgets · ownership</text><text x="590" y="112" text-anchor="middle" font-size="18" fill="#c9d1fb">orchestrates the agents</text>
 <rect x="910" y="20" width="250" height="96" rx="16" fill="#eef1ff"/><text x="1035" y="62" text-anchor="middle" font-size="24" font-weight="800" fill="#141c40">gpt-6-luna</text><text x="1035" y="92" text-anchor="middle" font-size="18" fill="#4d5679">via Portkey · logged</text>
 <line x1="250" y1="68" x2="434" y2="68" stroke="#4d5679" stroke-width="3" marker-end="url(#a)"/><line x1="740" y1="68" x2="904" y2="68" stroke="#4d5679" stroke-width="3" marker-end="url(#a)"/>
 <g font-size="18" fill="#4d5679" text-anchor="middle">
  <rect x="20" y="210" width="360" height="130" rx="16" fill="#fff" stroke="#8b9cf7" stroke-width="3"/><text x="200" y="250" font-size="26" font-weight="800" fill="#141c40">DecodeAgent</text><text x="200" y="282">explains phrases, power dynamics,</text><text x="200" y="306">unknowns, questions to ask</text><text x="200" y="330">JSON schema · cached per scenario</text>
  <rect x="410" y="210" width="360" height="130" rx="16" fill="#fff" stroke="#8b9cf7" stroke-width="3"/><text x="590" y="250" font-size="26" font-weight="800" fill="#141c40">RoleplayAgent</text><text x="590" y="282">plays the character, each turn</text><text x="590" y="306">has private motives, pushes back</text><text x="590" y="330">output guard on every reply</text>
  <rect x="800" y="210" width="360" height="130" rx="16" fill="#fff" stroke="#8b9cf7" stroke-width="3"/><text x="980" y="250" font-size="26" font-weight="800" fill="#141c40">FeedbackAgent</text><text x="980" y="282">reviews the full transcript</text><text x="980" y="306">6-part JSON · quotes verified</text><text x="980" y="330">ends with one retry challenge</text>
  <rect x="20" y="380" width="360" height="62" rx="12" fill="#eef1ff"/><text x="200" y="418" font-family="ui-monospace,Menlo,monospace" fill="#1e2a5a">lookup_workplace_knowledge</text>
  <rect x="410" y="380" width="360" height="62" rx="12" fill="#eef1ff"/><text x="590" y="418" font-family="ui-monospace,Menlo,monospace" fill="#1e2a5a">get_scenario_facts</text>
  <rect x="800" y="380" width="360" height="62" rx="12" fill="#eef1ff"/><text x="980" y="418" font-family="ui-monospace,Menlo,monospace" fill="#1e2a5a">get_workplace_guidance</text>
 </g>
 <line x1="590" y1="126" x2="200" y2="204" stroke="#4d5679" stroke-width="3" marker-end="url(#a)"/>
 <line x1="590" y1="126" x2="590" y2="204" stroke="#4d5679" stroke-width="3" marker-end="url(#a)"/>
 <line x1="590" y1="126" x2="980" y2="204" stroke="#4d5679" stroke-width="3" marker-end="url(#a)"/>
 <line x1="770" y1="275" x2="794" y2="275" stroke="#3b5bdb" stroke-width="4" marker-end="url(#a)"/>
 <line x1="200" y1="340" x2="200" y2="376" stroke="#8b9cf7" stroke-width="3" marker-end="url(#a)"/><line x1="590" y1="340" x2="590" y2="376" stroke="#8b9cf7" stroke-width="3" marker-end="url(#a)"/><line x1="980" y1="340" x2="980" y2="376" stroke="#8b9cf7" stroke-width="3" marker-end="url(#a)"/>
</svg>"""

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SkillSim Lite · Final Presentation</title>
<!-- reveal.js 5.1.0 from the jsDelivr CDN (needs internet). Without it, the built-in fallback at the end of
     this file still shows one slide at a time: arrow keys / space to move, F for full screen. -->
<link rel="stylesheet" href="{REVEAL}/reveal.css">
<link rel="stylesheet" href="{REVEAL}/theme/white.css">
<style>{CSS}</style></head>
<body><div class="reveal"><div class="slides">

<section class="title-slide">
 <div class="cols w60" style="align-items:center;height:100%">
  <div>
   <div class="brand"><span class="mark"></span>SkillSim</div>
   <h1>SkillSim Lite</h1>
   <p class="lede">Practice the conversations nobody teaches you how to have.</p>
   <p class="small">Alice Liang · AI Foundations · Final Project</p>
  </div>
  {img_landing}
 </div>
</section>

<section>
 <div class="kicker">The problem</div>
 <h2>The rules are real. They just aren't written down.</h2>
 <div class="cols">
  <div>
   <div class="phrase"><b>“Let me see what I can do.”</b><span>Real flexibility, or a polite close?</span></div>
   <div class="phrase"><b>“It's been a lot.”</b><span>An invitation to ask more, or a deflection?</span></div>
   <div class="phrase"><b>“This will show up in your review.”</b><span>Information, or a threat?</span></div>
  </div>
  <div>
   <div class="card" style="margin-bottom:18px"><div class="big">78%</div><div class="big-l">of employers seek verbal communication skills on a résumé (72% written) [1]</div></div>
   <p style="font-size:24px">First-generation graduates <i>“might not be aware of certain ‘unwritten rules’”</i> at work [2].</p>
  </div>
 </div>
 <div class="src">[1] NACE Job Outlook 2026 Spring Update, via Iowa State Univ. Career Services · [2] OPB, Sept. 1, 2022</div>
</section>

<section>
 <div class="kicker">The user <span class="tag h">Hypothesis · not yet validated</span></div>
 <h2>Who we think needs this first</h2>
 <div class="cols">
  <div>
   <ul>
    <li><b>First-generation students</b> without a family network in professional offices</li>
    <li><b>Early-career professionals</b> heading into relationship-driven industries</li>
    <li><b>International students</b> entering U.S. workplaces for the first time</li>
   </ul>
   <p class="honest">No user research yet. The study protocol is ready (10–15 min per person, with consent options).</p>
  </div>
  <div>
   <div class="stats three" style="grid-template-columns:1fr">
    <div class="stat"><div class="n">1,177,766</div><div class="l">international students in the U.S., 2024/25 [3]</div></div>
    <div class="stat"><div class="n">294,253</div><div class="l">of them on Optional Practical Training, working in U.S. jobs [3]</div></div>
   </div>
  </div>
 </div>
 <div class="src">[3] Institute of International Education, Open Doors 2025</div>
</section>

<section>
 <div class="kicker">Our solution</div>
 <h2>Decode → Rehearse → Reflect → Retry</h2>
 <div class="flow">
  <div class="step"><div class="num">1</div><b>Decode</b><span>What phrases may mean, the power dynamics, what you can't know, questions to ask.</span></div>
  <div class="step"><div class="num">2</div><b>Rehearse</b><span>A character with private motives who pushes back in proportion to how you handle it.</span></div>
  <div class="step"><div class="num">3</div><b>Reflect</b><span>Feedback built on your own quoted words. Interpretations framed as possibilities.</span></div>
  <div class="step"><div class="num">4</div><b>Retry</b><span>One specific challenge, then a side-by-side comparison of both attempts.</span></div>
 </div>
 <p class="honest"><b>Honestly:</b> AI role-play already exists (Yoodli, Second Nature), and Huru's feedback already quotes users. Our focus is <b>decoding unwritten expectations</b> and <b>feedback the server verifies</b>.</p>
</section>

<section>
 <div class="kicker">Agent architecture</div>
 <h2>Three agents, one orchestrator, read-only tools</h2>
 {ARCH}
 <p class="small" style="margin-top:6px">Each tool takes one enumerated argument and reads curated data already in memory. No tool can open a file. Instructions, scenario data and user text travel in separate channels.</p>
</section>

<section>
 <div class="kicker">Product demo · real screenshots</div>
 <div class="grid4">{img_scen}{img_decode}{img_chat}{img_fb}</div>
</section>

<section>
 <div class="kicker">Tokenomics <span class="tag m">Measured</span></div>
 <h2>About a fifth of a cent per practice session</h2>
 <div class="stats">
  <div class="stat"><div class="n">{cost}</div><div class="l">mean cost per simulation ({runs} fresh runs)</div></div>
  <div class="stat"><div class="n">{n_in}</div><div class="l">input tokens · {cache_pct}% cached</div></div>
  <div class="stat"><div class="n">{n_out}</div><div class="l">output tokens</div></div>
  <div class="stat"><div class="n">{reqs}</div><div class="l">model requests (4 user turns + feedback)</div></div>
 </div>
 <div class="kicker">Projection <span class="tag p">{spm} sessions / user / month</span></div>
 <div class="stats three proj">
  <div class="stat"><div class="n">{pu}</div><div class="l">per user / month</div></div>
  <div class="stat"><div class="n">{u100}</div><div class="l">100 users / month</div></div>
  <div class="stat"><div class="n">{u10k}</div><div class="l">10,000 users / month (high {u10k_hi})</div></div>
 </div>
 <p class="small">{lookup_share}% of input tokens are fact-lookup requests. Compact context made each request {drop_lo}–{drop_hi}% smaller, but no session-level saving is claimed (within noise). Costs are upper bounds: no cached-token price is published (${price_in} in / ${price_out} out per 1M).</p>
</section>

<section>
 <div class="kicker">Safety</div>
 <h2>Defenses we built, then attacked</h2>
 <div class="cols">
  <div>
   <table class="mini">
    <tr><th>Risk</th><th>Defense</th></tr>
    <tr><td>Prompt injection</td><td>Separate channels · flagged</td></tr>
    <tr><td>Secret leaks</td><td>Keys server-only · redacted</td></tr>
    <tr><td>Tool misuse</td><td>Enum-only, read-only tools</td></tr>
    <tr><td>Runaway cost</td><td>Turn, token &amp; daily caps</td></tr>
    <tr><td>Fake authority</td><td>Output guard · regenerate</td></tr>
    <tr><td>Invented feedback</td><td>Schema + quote verification</td></tr>
    <tr><td>Private transcripts</td><td>Per-browser ownership</td></tr>
   </table>
   <div class="stats" style="grid-template-columns:1fr 1fr;margin-top:16px">
    <div class="stat"><div class="n">{sec_pass}/{sec_total}</div><div class="l">live attacks on the real model passed</div></div>
    <div class="stat"><div class="n">{tests_ran}</div><div class="l">offline tests passing</div></div>
   </div>
  </div>
  <div>{img_defense}
   <p class="small" style="margin-top:10px"><b>Testing found a real bug:</b> a turn could spend tokens before hitting the budget. Fixed: the over-budget turn now gets HTTP 429 with {refused_calls} model calls.</p></div>
 </div>
</section>

<section>
 <div class="kicker">Impact</div>
 <h2>What we've actually measured, and what we haven't</h2>
 <div class="note" style="margin-bottom:18px"><b>No real users have tested SkillSim yet</b> ({n_participants} participant records). Everything below is internal and automated.</div>
 <table class="mini">
  <tr><th>Same scenario, {reps} scripted runs each</th><th class="r">Plain chatbot (same model)</th><th class="r">SkillSim</th></tr>
  <tr><td>User lines quoted in feedback (of 4)</td><td class="r">{q_b}</td><td class="r"><b>{q_c}</b></td></tr>
  <tr><td>Figures invented by the character</td><td class="r">{inv_b}</td><td class="r">{inv_c}</td></tr>
  <tr><td>Model wait per run</td><td class="r">{t_b} s</td><td class="r">{t_c} s</td></tr>
  <tr><td>Cost per run</td><td class="r">{c_b}</td><td class="r">{c_c}</td></tr>
 </table>
 <ul style="font-size:23px;margin-top:14px">
  <li>More specific feedback, but about {speed_x}× slower and {cost_x}× costlier than a plain chatbot.</li>
  <li>Our hypothesis that SkillSim invents fewer facts was <b>not supported</b>: neither invented any.</li>
  <li>Scores track an obvious contrast: a deliberately weak attempt scored <b>{cal_weak}</b>, a strong one <b>{cal_strong}</b>.</li>
 </ul>
</section>

<section>
 <div class="kicker">The future of SkillSim</div>
 <h2>From prototype to a library of unwritten rules</h2>
 <div class="cols">
  <div class="card">
   <h3>Limits today</h3>
   <ul style="font-size:23px">
    <li>Local prototype, text only, 3 scenarios</li>
    <li>Feedback checked for <i>form</i>, not yet for <i>truth</i></li>
    <li>Knowledge base: US-centric, one author</li>
    <li>Character can agree to a figure the user names</li>
   </ul>
  </div>
  <div class="card">
   <h3>Next month</h3>
   <ul style="font-size:23px">
    <li>Usability study with ≥5 people from the target groups</li>
    <li>Career advisor rates the outputs blind</li>
    <li>Scenario authoring with career centers</li>
    <li>Deploy with accounts and encrypted storage; then voice</li>
   </ul>
  </div>
 </div>
 <p class="lede" style="margin-top:24px;font-size:28px">The goal: <b>the conversations nobody teaches</b>, decoded honestly and practiced until they feel familiar.</p>
</section>

</div></div>
<script src="{REVEAL}/reveal.js"></script>
{FALLBACK}
</body></html>
"""


def main_cli():
    text = build()
    (ROOT / "slides.html").write_text(text)
    print(f"Wrote slides.html ({len(text) / 1e6:.2f} MB, {text.count('<section')} slides)")


if __name__ == "__main__":
    main_cli()
