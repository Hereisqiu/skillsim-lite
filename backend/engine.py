"""Conversation engines. Both return the same shapes, so the API and UI don't care which runs.

    opening(scenario)               -> ai message dict
    reply(scenario, session)        -> ai message dict      (appends to session["trace"])
    feedback(scenario, session)     -> feedback dict        (appends to session["trace"])
    decode(scenario)                -> decode dict          (cached per scenario)

LiveEngine (default) calls the model. MockEngine runs only with SKILLSIM_ENGINE=mock
and labels everything it produces as mock.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone

from . import config
from .agents import DECODE_INSTRUCTIONS, DecodeAgent, FeedbackAgent, RoleplayAgent
from .tools import KNOWLEDGE
from .llm import Budget, BudgetError, ModelClient, Usage, trace_event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stats(messages: list[dict]) -> dict:
    user = [m["text"] for m in messages if m["role"] == "user"]
    return {"user_turns": len(user), "questions_asked": sum(t.count("?") for t in user)}


def _budget(session: dict, prices: dict | None) -> Budget:
    context = {"session_id": session["id"], "scenario_id": session["scenario_id"],
               "variant": session.get("variant", config.CONTEXT_MODE), "run_tag": session.get("run_tag")}
    return Budget(session_tokens(session), prices, context)


def session_tokens(session: dict) -> int:
    total = 0
    for item in [*session["messages"], session.get("feedback") or {}]:
        u = item.get("usage")
        if u:
            total += u["input_tokens"] + u["output_tokens"]
    return total


class LiveEngine:
    source = "live"

    def __init__(self):
        self.client = ModelClient()
        self.model = self.client.model
        self.prices = self.client.prices
        self.roleplay = RoleplayAgent(self.client)
        self.coach = FeedbackAgent(self.client)
        self.decoder = DecodeAgent(self.client)

    def opening(self, scenario: dict) -> dict:
        # The scripted opening line costs nothing and sets the scene consistently.
        return {"role": "ai", "text": scenario["opening_line"], "ts": _now(), "source": "scripted",
                "usage": Usage().to_dict(self.prices), "latency_ms": 0}

    def reply(self, scenario: dict, session: dict) -> dict:
        budget = _budget(session, self.prices)
        # Pre-flight: a turn is several calls (lookups + reply), so refuse it up front if a turn like the
        # last one would cross the session budget, instead of spending tokens and failing midway.
        last = next((m.get("usage") for m in reversed(session["messages"]) if m["role"] == "ai" and m.get("usage")), None)
        estimate = (last["input_tokens"] + last["output_tokens"]) if last else 0
        if budget.session_tokens_used + estimate > config.SESSION_TOKEN_BUDGET:
            trace_event(session["trace"], "roleplay", "guardrail", {
                "rule": "session_budget_preflight", "used": budget.session_tokens_used, "next_turn_estimate": estimate,
                "budget": config.SESSION_TOKEN_BUDGET, "action": "turn refused before any model call"})
            raise BudgetError("This session has used its token budget. End the conversation to see your feedback.")
        text, usage, latency, tool_items = self.roleplay.reply(scenario, session["messages"], session["trace"], budget)
        return {"role": "ai", "text": text, "ts": _now(), "source": self.source, "model": self.model,
                "usage": usage.to_dict(self.prices), "latency_ms": latency, "_tools": tool_items}

    def feedback(self, scenario: dict, session: dict) -> dict:
        stats = _stats(session["messages"])
        if stats["user_turns"] == 0:
            # Nothing to evaluate, so don't spend tokens on it.
            trace_event(session["trace"], "feedback", "guardrail", {"rule": "empty_conversation", "action": "skipped model call"})
            return {**_empty_feedback(scenario), "stats": stats, "source": "rule",
                    "usage": Usage().to_dict(self.prices), "latency_ms": 0}
        budget = _budget(session, self.prices)
        data, usage, latency = self.coach.evaluate(scenario, session["messages"], session["trace"], budget)
        return {**data, "stats": stats, "source": self.source, "model": self.model,
                "usage": usage.to_dict(self.prices), "latency_ms": latency}

    def decode(self, scenario: dict) -> dict:
        """The decode guide depends only on the scenario and curated notes, so it is generated once
        per scenario and served from cache until those inputs change."""
        key = _decode_key(scenario)
        with _decode_lock:
            cache = _load_decode_cache()
            hit = cache.get(scenario["id"])
            if hit and hit["key"] == key:
                return {**hit, "cached": True}
            trace: list = []
            budget = Budget(0, self.prices, {"scenario_id": scenario["id"], "variant": config.CONTEXT_MODE})
            data, usage, latency = self.decoder.decode(scenario, trace, budget)
            entry = {**data, "key": key, "basis": KNOWLEDGE["about"], "source": self.source, "model": self.model,
                     "generated_at": _now(), "usage": usage.to_dict(self.prices), "latency_ms": latency, "trace": trace}
            cache[scenario["id"]] = entry
            DECODE_CACHE.write_text(json.dumps(cache, indent=2))
            return {**entry, "cached": False}


DECODE_CACHE = config.DATA_DIR / "decode_cache.json"
_decode_lock = threading.Lock()


def _decode_key(scenario: dict) -> str:
    public = {k: scenario[k] for k in ("context", "relationship", "power_dynamics", "objective", "opening_line")}
    material = json.dumps([public, KNOWLEDGE["scenarios"].get(scenario["id"]), KNOWLEDGE["general"], DECODE_INSTRUCTIONS], sort_keys=True)
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _load_decode_cache() -> dict:
    try:
        return json.loads(DECODE_CACHE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _empty_feedback(scenario: dict) -> dict:
    return {
        "overall": 0,
        "what_happened": "The conversation ended before you responded, so there is nothing to review yet.",
        "effective": [],
        "opportunity": {"moment_quote": "", "description": "Respond to the opening line to start the conversation."},
        "interpretation": {"quote": "", "possibility": ""},
        "alternative": {"response": "", "style": "", "why": ""},
        "retry_challenge": "Reply to the opening line and keep the conversation going for at least three turns.",
        "skills": [{"name": c["skill"], "score": 1, "evidence": "", "note": "No responses to assess.",
                    "description": c["description"]} for c in scenario["feedback_criteria"]],
    }


MOCK_SCRIPTS = {
    "tough-feedback": [
        "Oh. Yeah, I know the last few sprints have been rough. Honestly, it's been a lot.",
        "It's not that I don't care. I've been pulled into the rebrand work too, and nobody took anything off my plate.",
        "Okay, that's fair. If we can move the rebrand reviews to Fridays, I think I can hit Thursday's handoff.",
    ],
    "salary-negotiation": [
        "That's great to hear. I'll be upfront: $92,000 is a strong number for this level on our side.",
        "I may have a little room on base, but I'd need to take it back to the hiring manager.",
        "Let me put that in front of the team today. Can I get back to you by Thursday?",
    ],
    "upset-client": [
        "I appreciate that, but sorry doesn't help me with my CEO. I need to know this won't happen again.",
        "Okay. So what's actually different this time? Why should I trust the new date?",
        "Fine. I'll need something in writing I can forward to leadership today.",
    ],
}


class MockEngine:
    """Scripted lines and heuristic scores for UI demos. Everything is labeled mock."""

    source = "mock"
    model = "mock"
    prices = config.price_for(config.COURSE_MODEL)

    def _usage(self, text: str) -> dict:
        return Usage(400 + len(text) // 4, 0, len(text) // 4, calls=1, estimated=True).to_dict(self.prices)

    def opening(self, scenario: dict) -> dict:
        return {"role": "ai", "text": scenario["opening_line"], "ts": _now(), "source": "scripted",
                "usage": Usage().to_dict(self.prices), "latency_ms": 0}

    def reply(self, scenario: dict, session: dict) -> dict:
        script = MOCK_SCRIPTS.get(scenario["id"], [])
        n = sum(1 for m in session["messages"] if m["role"] == "user")
        text = script[n - 1] if 0 < n <= len(script) else "I think we've covered it. Anything else before we wrap up?"
        trace_event(session["trace"], "mock", "model_call", {"note": "mock engine, no API call"})
        return {"role": "ai", "text": text, "ts": _now(), "source": self.source, "usage": self._usage(text), "latency_ms": 0}

    def feedback(self, scenario: dict, session: dict) -> dict:
        stats = _stats(session["messages"])
        fb = _empty_feedback(scenario)
        user = [m["text"] for m in session["messages"] if m["role"] == "user"]
        if user:
            fb.update(overall=60, what_happened="Mock feedback: connect the model for a real review.",
                      effective=[{"behavior": "Mock: you responded.", "quote": user[0][:80]}],
                      retry_challenge="Mock challenge: ask one open question.")
        return {**fb, "stats": stats, "source": self.source, "usage": self._usage(json.dumps(fb)), "latency_ms": 0}

    def decode(self, scenario: dict) -> dict:
        kb = KNOWLEDGE["scenarios"].get(scenario["id"], {})
        return {"phrases": [{"phrase": k, "possible_meanings": [v], "depends_on": "Mock: no model call."}
                            for k, v in list(kb.get("phrases", {}).items())[:4]],
                "dynamics": kb.get("dynamics", []), "uncertainties": kb.get("uncertainties", []),
                "clarifying_questions": kb.get("questions", []), "basis": KNOWLEDGE["about"], "source": self.source,
                "usage": self._usage(""), "latency_ms": 0, "cached": False, "trace": []}


def get_engine():
    """Returns (engine, error). A misconfigured live engine is reported, never swapped for the mock."""
    if config.ENGINE == "mock":
        return MockEngine(), None
    try:
        return LiveEngine(), None
    except ValueError as exc:
        return None, str(exc)
