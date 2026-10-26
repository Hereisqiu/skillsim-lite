"""The single model client: one auth path, bounded retries, usage accounting.

Uses the OpenAI SDK's Responses API, pointed at the course Portkey gateway
(same pattern as the course examples) or at OpenAI directly.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass

import openai
from openai import OpenAI

from . import config, ledger, security, spend


class ModelError(Exception):
    """A model call failed. `user_message` is safe to show in the browser."""

    def __init__(self, user_message: str, status: int = 503):
        super().__init__(user_message)
        self.user_message = user_message
        self.status = status


class BudgetError(ModelError):
    def __init__(self, user_message: str):
        super().__init__(user_message, status=429)


@dataclass
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0          # sum over calls that reported it
    output_tokens: int = 0
    calls: int = 0
    cached_unreported_calls: int = 0      # calls whose response had no cached-token field
    estimated: bool = False

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.output_tokens += other.output_tokens
        self.calls += other.calls
        self.cached_unreported_calls += other.cached_unreported_calls
        self.estimated = self.estimated or other.estimated

    def to_dict(self, prices: dict | None) -> dict:
        cost = config.cost_usd(prices, self.input_tokens, self.cached_input_tokens, self.output_tokens)
        all_unreported = self.calls > 0 and self.cached_unreported_calls == self.calls
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": None if all_unreported else self.cached_input_tokens,
            "cached_partial": 0 < self.cached_unreported_calls < self.calls,
            "output_tokens": self.output_tokens,
            "model_calls": self.calls,
            "cost_usd": round(cost, 6) if cost is not None else None,
            "estimated": self.estimated,
        }


def _detail(obj, name):
    """A usage detail field, or None if the API didn't send it."""
    value = getattr(obj, name, None) if obj is not None else None
    return value if isinstance(value, int) else None


def usage_from(response) -> Usage:
    u = response.usage
    cached = _detail(getattr(u, "input_tokens_details", None), "cached_tokens")
    return Usage(u.input_tokens, cached or 0, u.output_tokens, calls=1, cached_unreported_calls=int(cached is None))


TRANSIENT = (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError)


class Budget:
    """Spend guard for one request: checks the session and daily caps before every call.
    Also carries the request context (session, scenario, variant) that the ledger records."""

    def __init__(self, session_tokens_used: int, prices: dict | None, context: dict | None = None):
        self.session_tokens_used = session_tokens_used
        self.prices = prices
        self.context = context or {}

    def check(self) -> None:
        if self.session_tokens_used >= config.SESSION_TOKEN_BUDGET:
            raise BudgetError("This session has used its token budget. End the conversation to see your feedback.")
        day = spend.today()
        if day["tokens"] >= config.DAILY_TOKEN_BUDGET or day["cost_usd"] >= config.DAILY_COST_BUDGET_USD:
            raise BudgetError("SkillSim has reached its daily usage limit. Please try again tomorrow.")

    def record(self, usage: Usage) -> None:
        self.session_tokens_used += usage.total
        cost = config.cost_usd(self.prices, usage.input_tokens, usage.cached_input_tokens, usage.output_tokens)
        spend.record(usage.total, cost or 0.0)


class ModelClient:
    def __init__(self):
        s = config.provider_settings()
        self.provider = s["provider"]
        self.model = s["model"]
        self.prices = s["prices"]
        # The SDK's own retries are off so every attempt is visible in the trace and the ledger.
        self._client = OpenAI(
            api_key=s["api_key"],
            base_url=s["base_url"],
            default_headers=s["headers"] or None,
            timeout=config.REQUEST_TIMEOUT_S,
            max_retries=0,
        )
        # Benchmarks must measure fresh model calls, not gateway replays.
        self._extra_headers = ({"x-portkey-cache-force-refresh": "true"}
                               if config.GATEWAY_CACHE_REFRESH and self.provider == "portkey" else {})

    def _ledger(self, budget: Budget, agent: str, operation: str, attempt: int, latency: int,
                response=None, error: str | None = None, headers=None) -> None:
        row = {
            "ts": time.time(), "request_id": uuid.uuid4().hex[:12],
            "session_id": budget.context.get("session_id"), "scenario_id": budget.context.get("scenario_id"),
            "variant": budget.context.get("variant", config.CONTEXT_MODE), "run_tag": budget.context.get("run_tag"),
            "provider": self.provider, "model": self.model, "agent": agent, "operation": operation, "attempt": attempt,
            "latency_ms": latency, "error": error, "status": None,
            "input_tokens": None, "cached_input_tokens": None, "cache_write_tokens": None,
            "output_tokens": None, "reasoning_tokens": None, "cost_usd": None,
            "cost_basis": config.cost_basis(self.prices), "tool_calls": [],
            # Portkey's own response cache: HIT means the gateway replayed a stored response (and its
            # original usage numbers) without a new model call. None = header not sent.
            "gateway_cache": headers.get("x-portkey-cache-status") if headers is not None else None,
            "routed_provider": headers.get("x-portkey-provider") if headers is not None else None,
        }
        if response is not None:
            u = response.usage
            in_details, out_details = getattr(u, "input_tokens_details", None), getattr(u, "output_tokens_details", None)
            row.update(
                status=response.status, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                cached_input_tokens=_detail(in_details, "cached_tokens"),
                cache_write_tokens=_detail(in_details, "cache_write_tokens"),
                reasoning_tokens=_detail(out_details, "reasoning_tokens"),
                tool_calls=[item.name for item in response.output if item.type == "function_call"],
            )
            cost = config.cost_usd(self.prices, u.input_tokens, row["cached_input_tokens"], u.output_tokens)
            row["cost_usd"] = round(cost, 8) if cost is not None else None
        ledger.record(row)

    def create(self, *, agent: str, trace: list, budget: Budget, operation: str | None = None, **kwargs):
        """One Responses API call with bounded retries on transient errors. Every attempt is logged."""
        operation = operation or agent
        budget.check()
        for attempt in range(1, config.MAX_RETRIES + 2):
            start = time.perf_counter()
            try:
                raw = self._client.responses.with_raw_response.create(
                    model=self.model, extra_headers=self._extra_headers or None, **kwargs)
                response, headers = raw.parse(), raw.headers
            except TRANSIENT as exc:
                latency = int((time.perf_counter() - start) * 1000)
                self._ledger(budget, agent, operation, attempt, latency, error=type(exc).__name__)
                trace_event(trace, agent, "retry" if attempt <= config.MAX_RETRIES else "error",
                            {"attempt": attempt, "error": type(exc).__name__, "latency_ms": latency})
                if attempt > config.MAX_RETRIES:
                    raise ModelError("The AI service is busy right now. Please try sending again in a moment.") from exc
                time.sleep(min(8, 2 ** (attempt - 1)) + random.random() * 0.5)
                continue
            except openai.AuthenticationError as exc:
                self._ledger(budget, agent, operation, attempt, int((time.perf_counter() - start) * 1000), error="AuthenticationError")
                trace_event(trace, agent, "error", {"attempt": attempt, "error": "AuthenticationError"})
                raise ModelError("The server's API key was rejected. Check the key in .env.", 502) from exc
            except openai.APIStatusError as exc:
                latency = int((time.perf_counter() - start) * 1000)
                if exc.status_code == 400 and ("content management policy" in str(exc) or "content_filter" in str(exc)):
                    self._ledger(budget, agent, operation, attempt, latency, error="ContentFilter")
                    trace_event(trace, agent, "guardrail", {"rule": "provider_content_filter", "attempt": attempt,
                                                           "action": "request refused upstream; message not added"})
                    raise ModelError("That message was blocked by the AI provider's safety filter. "
                                     "Please rephrase it and keep to the conversation.", 422) from exc
                self._ledger(budget, agent, operation, attempt, latency, error=f"{type(exc).__name__} {exc.status_code}")
                trace_event(trace, agent, "error", {"attempt": attempt, "error": type(exc).__name__,
                                                   "status": exc.status_code, "message": str(exc)[:300]})
                raise ModelError("The AI service couldn't process that request. Please try again.", 502) from exc

            latency = int((time.perf_counter() - start) * 1000)
            usage = usage_from(response)
            budget.record(usage)
            self._ledger(budget, agent, operation, attempt, latency, response=response, headers=headers)
            trace_event(trace, agent, "model_call", {
                "attempt": attempt, "latency_ms": latency, "model": self.model, "operation": operation,
                "usage": usage.to_dict(self.prices), "status": response.status,
            })
            return response, usage, latency
        raise AssertionError("unreachable")


def trace_event(trace: list, agent: str, event: str, detail: dict) -> None:
    # Error messages and echoed text are redacted so a key can never land in a stored trace.
    trace.append({"ts": time.time(), "agent": agent, "event": event, "detail": security.redact(detail)})
