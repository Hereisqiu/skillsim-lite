"""Structured-output schemas. The same Pydantic models generate the strict JSON schema sent to
the model and validate what comes back."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- feedback ----

class EffectiveMove(_Strict):
    behavior: str
    quote: str


class Opportunity(_Strict):
    moment_quote: str
    description: str


class Interpretation(_Strict):
    quote: str
    possibility: str


class Alternative(_Strict):
    response: str
    style: str
    why: str


class SkillScore(_Strict):
    name: str
    score: int
    evidence: str
    note: str


class FeedbackOut(_Strict):
    what_happened: str
    effective: list[EffectiveMove]
    opportunity: Opportunity
    interpretation: Interpretation
    alternative: Alternative
    retry_challenge: str
    skills: list[SkillScore]


# ---- decode this situation ----

class PhraseMeaning(_Strict):
    phrase: str
    possible_meanings: list[str]
    depends_on: str


class DecodeOut(_Strict):
    phrases: list[PhraseMeaning]
    dynamics: list[str]
    uncertainties: list[str]
    clarifying_questions: list[str]


def strict_schema(model: type[BaseModel], name: str) -> dict:
    """Responses API `text.format` for a model: refs inlined, titles dropped, every field required."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def clean(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return clean(defs[node["$ref"].split("/")[-1]])
            node = {k: clean(v) for k, v in node.items() if k != "title"}
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            return node
        if isinstance(node, list):
            return [clean(n) for n in node]
        return node

    return {"type": "json_schema", "name": name, "strict": True, "schema": clean(schema)}
