"""SkillSim API + static frontend. Keys stay on the server; the browser only sees this API."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, ledger, measure, security, spend, store
from .engine import get_engine, session_tokens
from .llm import ModelError, trace_event

app = FastAPI(title="SkillSim")


@app.middleware("http")
async def no_cache_frontend(request, call_next):
    """Always serve the current frontend files, so code updates show up without a hard refresh."""
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response
engine, engine_error = get_engine()

SCENARIOS: list[dict] = json.loads((config.DATA_DIR / "scenarios.json").read_text())
SCENARIOS_BY_ID = {s["id"]: s for s in SCENARIOS}
PRIVATE_FIELDS = {"private_motivations", "resistance", "boundaries", "facts", "guidance_topics"}

_session_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class StartRequest(BaseModel):
    scenario_id: str
    retry_of: str | None = None  # the earlier attempt this one retries, kept for comparison


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=config.MAX_MESSAGE_CHARS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public_scenario(s: dict) -> dict:
    """Scenario as the user sees it: no private motivations, facts, or character instructions."""
    out = {k: v for k, v in s.items() if k not in PRIVATE_FIELDS}
    out["ai_role"] = {k: s["ai_role"][k] for k in ("name", "title", "description")}
    out["skills"] = [c["skill"] for c in s["feedback_criteria"]]
    return out


def _scenario(scenario_id: str) -> dict:
    scenario = SCENARIOS_BY_ID.get(scenario_id)
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    return scenario


def _session(session_id: str) -> dict:
    session = store.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


def client_owner(x_skillsim_client: str | None = Header(default=None)) -> str:
    """Each browser sends a random client ID; sessions belong to a hash of it. Without the ID, no
    transcript can be read, and one browser can never see or delete another's sessions."""
    if not x_skillsim_client or not 16 <= len(x_skillsim_client) <= 128:
        raise HTTPException(401, "Missing client ID.")
    return hashlib.sha256(x_skillsim_client.encode()).hexdigest()[:32]


def _owned(session_id: str, owner: str) -> dict:
    session = store.get(session_id)
    if not session or session.get("owner") != owner:
        raise HTTPException(404, "Session not found")  # same answer whether it exists or not
    return session


LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


def require_dev(request: Request) -> None:
    """Developer views include traces and usage across all sessions: local requests only."""
    if not config.DEV_TOOLS:
        raise HTTPException(404, "Developer tools are disabled.")
    if (request.client.host if request.client else None) not in LOOPBACK:
        raise HTTPException(403, "Developer tools are only available on this machine.")


def _require_engine():
    if engine is None:
        raise HTTPException(503, f"The AI model isn't configured: {engine_error}")
    return engine


def _lock_for(session_id: str) -> threading.Lock:
    with _locks_guard:
        return _session_locks.setdefault(session_id, threading.Lock())


def _expire_if_idle(session: dict) -> None:
    if session["status"] != "active":
        return
    last = datetime.fromisoformat(session["last_activity"])
    if _now() - last > timedelta(minutes=config.SESSION_IDLE_TIMEOUT_MIN):
        session["status"] = "expired"
        trace_event(session["trace"], "api", "guardrail", {"rule": "session_timeout", "idle_minutes": config.SESSION_IDLE_TIMEOUT_MIN})
        store.put(session)


def _totals(session: dict) -> dict:
    calls = [m["usage"] for m in session["messages"] if m.get("usage")]
    if session.get("feedback"):
        calls.append(session["feedback"]["usage"])
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "model_calls")
    totals = {k: sum(c.get(k) or 0 for c in calls) for k in keys}
    costs = [c.get("cost_usd") for c in calls]
    totals["cost_usd"] = round(sum(c for c in costs if c), 6) if all(c is not None for c in costs) else None
    totals["latency_ms"] = sum(m.get("latency_ms", 0) for m in session["messages"]) + (
        session["feedback"]["latency_ms"] if session.get("feedback") else 0)
    totals["estimated"] = any(c.get("estimated") for c in calls)
    return totals


def _public(session: dict) -> dict:
    out = {k: v for k, v in session.items() if k not in ("trace", "owner")}  # the trace is developer-only
    # "_" keys (e.g. the character's tool lookups) hold private scenario data; never send them.
    out["messages"] = [{k: v for k, v in m.items() if not k.startswith("_")} for m in session["messages"]]
    out["totals"] = _totals(session)
    out["limits"] = {
        "max_user_turns": config.MAX_USER_TURNS,
        "max_message_chars": config.MAX_MESSAGE_CHARS,
        "idle_timeout_min": config.SESSION_IDLE_TIMEOUT_MIN,
        "session_token_budget": config.SESSION_TOKEN_BUDGET,
    }
    return out


@app.get("/api/health")
def health():
    info = config.describe_provider()
    if engine is None:
        info.update(ready=False, error=engine_error)
    return {**{k: v for k, v in info.items() if k != "prices"}, "dev_tools": config.DEV_TOOLS,
            "env_file_found": config.ENV_PATH is not None}


@app.get("/api/scenarios")
def list_scenarios():
    return [_public_scenario(s) for s in SCENARIOS]


@app.get("/api/scenarios/{scenario_id}")
def get_scenario(scenario_id: str):
    return _public_scenario(_scenario(scenario_id))


@app.get("/api/scenarios/{scenario_id}/decode")
def decode_scenario(scenario_id: str):
    eng = _require_engine()
    scenario = _scenario(scenario_id)
    try:
        data = eng.decode(scenario)
    except ModelError as exc:
        raise HTTPException(exc.status, exc.user_message)
    return {k: v for k, v in data.items() if k not in ("trace", "key")}


@app.post("/api/sessions")
def start_session(req: StartRequest, owner: str = Depends(client_owner)):
    eng = _require_engine()
    scenario = _scenario(req.scenario_id)
    previous = None
    if req.retry_of:
        previous = store.get(req.retry_of)
        if not previous or previous.get("owner") != owner or previous["scenario_id"] != scenario["id"]:
            raise HTTPException(400, "The attempt you're retrying wasn't found for this scenario.")
    mine = [s for s in store.all_sessions() if s.get("owner") == owner]
    attempt = 1 + sum(1 for s in mine if s["scenario_id"] == scenario["id"])
    now = _now().isoformat()
    session = {
        "id": uuid.uuid4().hex[:12],
        "owner": owner,
        "scenario_id": scenario["id"],
        "scenario_title": scenario["title"],
        "attempt": attempt,
        "status": "active",
        "engine": eng.source,
        "model": eng.model,
        "started_at": now,
        "last_activity": now,
        "ended_at": None,
        "messages": [eng.opening(scenario)],
        "feedback": None,
        "variant": config.CONTEXT_MODE,
        "retry_of": previous["id"] if previous else None,
        "retry_challenge": (previous.get("feedback") or {}).get("retry_challenge") if previous else None,
        "trace": [],
    }
    store.put(session)
    return _public(session)


@app.get("/api/sessions")
def list_sessions(owner: str = Depends(client_owner)):
    sessions = [s for s in store.all_sessions() if s.get("owner") == owner]
    for s in sessions:
        _expire_if_idle(s)
    return [_public(s) for s in sessions]


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, owner: str = Depends(client_owner)):
    session = _owned(session_id, owner)
    _expire_if_idle(session)
    return _public(session)


@app.post("/api/sessions/{session_id}/messages")
def send_message(session_id: str, req: MessageRequest, owner: str = Depends(client_owner)):
    eng = _require_engine()
    _owned(session_id, owner)
    if security.contains_secret(req.text):
        raise HTTPException(422, "That message looks like it contains an API key, so it wasn't sent. Please remove it.")
    lock = _lock_for(session_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "Still waiting on the last reply.")
    try:
        session = _session(session_id)
        _expire_if_idle(session)
        if session["status"] == "expired":
            raise HTTPException(410, f"This session timed out after {config.SESSION_IDLE_TIMEOUT_MIN} minutes idle. End it to get feedback, or start a new one.")
        if session["status"] != "active":
            raise HTTPException(409, "This conversation has ended.")
        user_turns = sum(1 for m in session["messages"] if m["role"] == "user")
        if user_turns >= config.MAX_USER_TURNS:
            raise HTTPException(429, "Turn limit reached. End the conversation to get feedback.")
        last_user = next((m for m in reversed(session["messages"]) if m["role"] == "user"), None)
        if last_user and (_now() - datetime.fromisoformat(last_user["ts"])).total_seconds() < config.MIN_SECONDS_BETWEEN_MESSAGES:
            raise HTTPException(429, "You're sending messages too quickly.")

        scenario = _scenario(session["scenario_id"])
        user_msg = {"role": "user", "text": req.text.strip(), "ts": _now().isoformat()}
        session["messages"].append(user_msg)
        try:
            ai_msg = eng.reply(scenario, session)
        except ModelError as exc:
            session["messages"].pop()  # the user can resend; a failed turn isn't counted
            store.put(session)
            raise HTTPException(exc.status, exc.user_message)
        session["messages"].append(ai_msg)
        session["last_activity"] = _now().isoformat()
        store.put(session)
        return _public(session)
    finally:
        lock.release()


@app.post("/api/sessions/{session_id}/end")
def end_session(session_id: str, owner: str = Depends(client_owner)):
    eng = _require_engine()
    _owned(session_id, owner)
    lock = _lock_for(session_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "Still working on this session.")
    try:
        session = _session(session_id)
        if session.get("feedback"):
            return _public(session)
        scenario = _scenario(session["scenario_id"])
        try:
            feedback = eng.feedback(scenario, session)
        except ModelError as exc:
            store.put(session)  # keep the trace of the failed attempt
            raise HTTPException(exc.status, exc.user_message)
        session["status"] = "ended"
        session["ended_at"] = _now().isoformat()
        session["feedback"] = feedback
        store.put(session)
        return _public(session)
    finally:
        lock.release()


@app.get("/api/metrics", dependencies=[Depends(require_dev)])
def metrics():
    all_sessions = store.all_sessions()
    # Averages use one engine only, so mock estimates never mix with real counts.
    current = "mock" if config.ENGINE == "mock" else "live"
    sessions = [s for s in all_sessions if s.get("engine", "mock") == current]
    totals = [_totals(s) for s in sessions]
    n = len(sessions)
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "model_calls", "latency_ms")
    summed = {k: sum(t[k] for t in totals) for k in keys}
    costs = [t["cost_usd"] for t in totals]
    summed["cost_usd"] = round(sum(c for c in costs if c), 6) if all(c is not None for c in costs) else None
    ended = [s for s in sessions if s.get("feedback")]
    info = config.describe_provider()
    return {
        "engine": info["engine"],
        "provider": info["provider"],
        "model": info["model"],
        "prices_per_million": info["prices"],
        "sessions": n,
        "excluded_sessions": len(all_sessions) - n,
        "completed": len(ended),
        "estimated": any(t["estimated"] for t in totals),
        "totals": summed,
        "per_session_avg": {
            k: (round(summed[k] / n) if summed[k] is not None and k != "cost_usd" else
                (round(summed[k] / n, 6) if summed[k] is not None else None)) if n else 0
            for k in ("input_tokens", "cached_input_tokens", "output_tokens", "cost_usd")
        },
        "avg_latency_ms": round(summed["latency_ms"] / summed["model_calls"]) if summed["model_calls"] else 0,
        "avg_score": round(sum(s["feedback"]["overall"] for s in ended) / len(ended)) if ended else None,
        "budgets": {
            "today": spend.today(),
            "daily_token_budget": config.DAILY_TOKEN_BUDGET,
            "daily_cost_budget_usd": config.DAILY_COST_BUDGET_USD,
            "session_token_budget": config.SESSION_TOKEN_BUDGET,
        },
    }


@app.get("/api/dev/sessions/{session_id}/trace", dependencies=[Depends(require_dev)])
def session_trace(session_id: str):
    session = _session(session_id)
    return {"id": session["id"], "scenario_title": session["scenario_title"], "attempt": session["attempt"],
            "engine": session.get("engine"), "model": session.get("model"),
            "tokens_used": session_tokens(session), "trace": session.get("trace", [])}


@app.get("/api/dev/decode/{scenario_id}/trace", dependencies=[Depends(require_dev)])
def decode_trace(scenario_id: str):
    from .engine import _load_decode_cache
    entry = _load_decode_cache().get(_scenario(scenario_id)["id"])
    if not entry:
        raise HTTPException(404, "This scenario hasn't been decoded yet.")
    return {"id": f"decode-{scenario_id}", "scenario_title": SCENARIOS_BY_ID[scenario_id]["title"], "attempt": "decode",
            "engine": entry.get("source"), "model": entry.get("model"),
            "tokens_used": entry["usage"]["input_tokens"] + entry["usage"]["output_tokens"], "trace": entry.get("trace", [])}


@app.get("/api/dev/usage", dependencies=[Depends(require_dev)])
def dev_usage(sessions_per_month: float = measure.DEFAULT_SESSIONS_PER_USER_MONTH):
    """Developer dashboard data: measured per-request usage plus clearly separated projections."""
    if not 0 < sessions_per_month <= 1000:
        raise HTTPException(400, "sessions_per_month must be between 0 and 1000.")
    return measure.report(store.all_sessions(), SCENARIOS_BY_ID, sessions_per_month)


@app.get("/api/dev/export/simulations.csv", dependencies=[Depends(require_dev)])
def export_simulations_csv():
    sims = measure.report(store.all_sessions(), SCENARIOS_BY_ID)["measured"]["simulations"]
    return Response(measure.simulations_csv(sims), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=skillsim_simulations.csv"})


@app.get("/api/dev/export/requests.csv", dependencies=[Depends(require_dev)])
def export_requests_csv():
    return Response(measure.requests_csv(ledger.read_all()), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=skillsim_requests.csv"})


@app.delete("/api/sessions")
def delete_my_sessions(owner: str = Depends(client_owner)):
    """Delete this browser's practice history (and only this browser's)."""
    removed = store.delete_where(lambda s: s.get("owner") == owner)
    return {"deleted": removed}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, owner: str = Depends(client_owner)):
    _owned(session_id, owner)
    store.delete_where(lambda s: s["id"] == session_id)
    return {"deleted": 1}


app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(config.FRONTEND_DIR / "index.html")
