# SkillSim Lite

**Practice the conversations nobody teaches you how to have.**

SkillSim Lite is a local web app for rehearsing difficult workplace conversations: giving tough feedback to a direct report, negotiating a job offer, and calming an upset client. Before practicing, you can *decode* the situation (what workplace phrases may mean, the power dynamics, what you can't know yet). Then you talk with an AI character who has private motivations and pushes back realistically. You get structured feedback that quotes your own words, along with one specific challenge to try on a retry.

- **App URL:** not deployed. It runs locally. Setup takes a few minutes from a fresh clone (measured: under a minute when pip has the packages cached).
- **Model:** `gpt-6-luna` through the AI Foundations Portkey gateway (course key).
- **Report and slides:** `report.html` and `slides.html` in this folder.

---

## Quick start (fresh clone)

**Prerequisites:** Python 3.10 or newer (developed and tested on Python 3.13, macOS) and internet access for the model API. No database or other services are needed.

**1. Put the API key where the app can find it.** The app reads `.env` from the project folder first, then from the folder *above* it for anything still missing. The grader layout works with no changes:

```
submissions/
├── .env              ← PORTKEY_API_KEY=... (read automatically)
└── skillsim-lite/    ← this repository
```

To use a local `.env` instead, copy the example and fill in the key:

```bash
cp .env.example .env
```

**2. Install and start** (from inside the project folder):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

On Windows, activate the virtual environment with `.venv\Scripts\activate` instead.

**3. Open http://127.0.0.1:8000** and choose a scenario. To use another port: `PORT=8050 python run.py`.

If the key is missing, the header shows **"AI not configured"** and the app explains what's wrong. It never silently switches to fake responses.

## Environment variables

| Name | Required | Purpose |
|---|---|---|
| `PORTKEY_API_KEY` | Yes (default path) | Course key. Used only with `gpt-6-luna` through `https://api.portkey.ai/v1`. |
| `OPENAI_API_KEY` | Only for the alternative path | Your own OpenAI account. Also set `SKILLSIM_PROVIDER=openai` and `OPENAI_MODEL=<model>`. Costs show as "unavailable" unless the model is listed in `pricing.json`. |

Optional settings (not keys): `PORT`, `SKILLSIM_DEV_TOOLS=0` (hides the developer views), `SKILLSIM_ENGINE=mock` (a UI demo with no model; every reply is labeled "Mock response"), and `SKILLSIM_CONTEXT` (`optimized` by default; `baseline` or `prefetch` for cost experiments).

## Features

- **Three scenarios:** delivering tough feedback, negotiating an offer, and calming an upset client. Each has roles, a relationship, power dynamics, and an objective.
- **Decode this situation:** possible meanings of workplace phrases, power dynamics, unknowns, and questions to ask. Grounded in a small curated knowledge base and labeled "not universal, not externally verified".
- **Role-play:** the character has private motivations, looks up scenario facts with a tool, and pushes back in proportion to how you handle the conversation.
- **Feedback:** what happened; what worked (with verified quotes); one opportunity; how a line *might* have landed; one alternative (labeled as one style among many); a retry challenge; and a skill check.
- **Retry and compare:** a retry carries the challenge into the next attempt, and two attempts can be compared side by side.
- **History:** visible only to the browser that created it, with "Delete my history".
- **Developer views** (local requests only): per-session traces of every model call, tool call, and guardrail event, plus a token and cost dashboard.

## Architecture

```
Browser (static HTML/CSS/JS, no keys)
   │  random per-browser client ID
   ▼
FastAPI server (backend/main.py)  ── limits, budgets, session ownership, orchestration
   ├─ DecodeAgent    ── tool: lookup_workplace_knowledge(section)  → data/knowledge_base.json
   ├─ RoleplayAgent  ── tool: get_scenario_facts(topic)            → data/scenarios.json "facts"
   └─ FeedbackAgent  ── tool: get_workplace_guidance(topic)        → data/guidance.json
   ▼
ModelClient (backend/llm.py) → Portkey → gpt-6-luna   (every request logged to data/requests.jsonl)
```

- The **server orchestrates**: agents never call each other. When you click *End*, the server sends the transcript to the FeedbackAgent.
- **Tools** are read-only. Each takes one enumerated argument and reads data already loaded in memory. No tool takes a path or opens a file.
- **Instructions, scenario data, and user text** are always sent in separate message channels.
- **Decode and Feedback** return JSON validated against Pydantic schemas (`backend/schemas.py`).

```
backend/    main.py (API) · engine.py · agents.py · schemas.py · llm.py · tools.py · security.py
            ledger.py · measure.py · spend.py · store.py · config.py · prompts/
data/       scenarios.json · guidance.json · knowledge_base.json  (runtime logs are git-ignored)
frontend/   index.html · app.js · styles.css
tests/      offline tests (no API calls)
scripts/    benchmark, exports, live security check, evaluation, report and slide builders
exports/    measured results used in the report
evaluation/ participant protocol, templates, internal evaluation
pricing.json  model prices with source, units, and date
```

## Tests

```bash
python -m unittest -v
```

The offline suite needs no API key and makes no API calls. It covers prompt injection, secret handling, tool access, budgets, structured-output validation, quote verification, transcript privacy, `.env` loading, measurement, and evaluation scripts.

## Usage metrics

- **In the app:** **History → Developer metrics.** The *Measured* section shows tokens by request, agent, and operation, and the cost per full simulation. A separate *Projection* section has adjustable assumptions. Click any session ID to see its full trace.
- **Raw log:** `data/requests.jsonl`, one line per model request with input, cached input, and output tokens, latency, cost, tool calls, errors, and gateway cache status.
- **Exports used in the report:** `exports/measurements.json`, `exports/simulations.csv`, `exports/requests.csv`, and `exports/cost_optimization.md`. To regenerate them:
  ```bash
  python -m scripts.export_measurements
  ```
- **Prices:** `pricing.json` ($0.10 input and $0.50 output per 1M tokens, from the course starter code). No cached-input rate is published, so cached tokens are billed at the input rate and every cost is an upper bound.

Scripts that call the real model (they cost a few cents):

```bash
python -m scripts.benchmark --reps 3
python -m scripts.live_security_check
python -m scripts.internal_evaluation
```

## Safety controls (implemented and tested)

| Risk | Control |
|---|---|
| Prompt injection | Separate channels; injection-like text flagged; provider content-filter refusals shown clearly |
| Secrets | Keys stay on the server; replies checked for secrets and leaked instructions; pasted keys refused; logs redacted |
| Tool misuse | Enumerated, read-only tools; unknown tools refused |
| Runaway cost | 1,200 characters per message; 12 turns; 1 message per second; 30-minute idle timeout; an 80,000-token session budget checked before each turn; daily token and cost caps; 2 retries on transient errors only; 45-second timeout |
| Character fabrications | Output guard against "as an AI" breaks, legal or official authority claims, and figures not in the scenario: regenerate once, then block |
| Invented feedback | Schema validation; quotes must appear verbatim in the user's words; praise without a quote dropped; personal-trait comments removed |
| Transcript privacy | Per-browser session ownership; developer views local-only; server binds to 127.0.0.1 |

Evidence: `exports/security_evidence.md` (live attacks against the real model) and `tests/test_security.py`.

## Limitations

- **Not deployed.** Transcripts are stored unencrypted in `data/sessions.json` on the local machine, and per-browser IDs are not accounts.
- **Text only, three scenarios.** The knowledge base reflects US-centric office norms and was written by one author.
- **Feedback is checked for form, not truth.** Schema, real quotes, and no trait judgments are enforced, but no human has yet rated whether its interpretations are accurate.
- **No real-user testing yet.** The protocol is ready in `evaluation/`, and the report's impact section is internal evidence only.
- **Known guard gap:** if the user names a figure first and the character agrees to it, the figure check doesn't fire.
- **Slides need internet** to load reveal.js from its CDN. Without it, a built-in fallback still shows one slide at a time (arrow keys, **F** for full screen).

## Rebuilding the report and slides

```bash
python -m scripts.build_report --repo-url https://github.com/<owner>/<repo>
python -m scripts.build_slides --repo-url https://github.com/<owner>/<repo>
```

Both run the test suite first, compute every number from the logs and exports, and embed screenshots from `report_assets/`. The report builder also reads the local session and request logs, which are git-ignored, so it rebuilds only on the machine that produced them.
