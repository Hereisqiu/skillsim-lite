"""Model-callable tools. Read-only, and limited to the approved local data files.

Each tool's `topic` argument is an enum of the keys that exist, so the model
can only ask for curated entries; anything else is refused by `run_tool`.
"""

from __future__ import annotations

import json

from . import config
from .config import DATA_DIR

GUIDANCE: dict = json.loads((DATA_DIR / "guidance.json").read_text())
KNOWLEDGE: dict = json.loads((DATA_DIR / "knowledge_base.json").read_text())
KNOWLEDGE_SECTIONS = ["phrases", "dynamics", "uncertainties", "questions", "general_norms"]


def scenario_facts_tool(scenario: dict) -> dict:
    return {
        "type": "function",
        "name": "get_scenario_facts",
        "description": (
            "Look up a curated fact your character knows (numbers, dates, names, workload, policies). "
            "Use it before stating any specific detail so you stay consistent."
        ),
        "parameters": {
            "type": "object",
            "properties": {"topic": {"type": "string", "enum": sorted(scenario["facts"])}},
            "required": ["topic"],
            "additionalProperties": False,
        },
        "strict": True,
    }


def guidance_tool(scenario: dict) -> dict:
    topics = [t for t in scenario.get("guidance_topics", []) if t in GUIDANCE] or sorted(GUIDANCE)
    return {
        "type": "function",
        "name": "get_workplace_guidance",
        "description": "Fetch a curated best-practice note to ground your feedback in an established technique.",
        "parameters": {
            "type": "object",
            "properties": {"topic": {"type": "string", "enum": topics}},
            "required": ["topic"],
            "additionalProperties": False,
        },
        "strict": True,
    }


def knowledge_tool(scenario: dict) -> dict:
    return {
        "type": "function",
        "name": "lookup_workplace_knowledge",
        "description": (
            "Read one section of SkillSim's curated notes for this scenario: common meanings of workplace "
            "phrases, power dynamics, open uncertainties, clarification questions, or general norms."
        ),
        "parameters": {
            "type": "object",
            "properties": {"section": {"type": "string", "enum": KNOWLEDGE_SECTIONS}},
            "required": ["section"],
            "additionalProperties": False,
        },
        "strict": True,
    }


def knowledge_section(scenario_id: str, section: str):
    """Raw curated entries for one section (used by the tool and by server-side grounding checks)."""
    if section == "general_norms":
        return KNOWLEDGE["general"]
    return KNOWLEDGE["scenarios"].get(scenario_id, {}).get(section)


def run_tool(name: str, raw_args: str, scenario: dict, allowed: set[str]) -> tuple[dict, str]:
    """Execute a tool call. Returns (parsed args, result text). Never writes anything."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return {}, "Error: arguments were not valid JSON."
    if name not in allowed:
        return args, f"Error: tool '{name}' is not available."
    topic = args.get("topic")
    if name == "get_scenario_facts":
        fact = scenario["facts"].get(topic)
        return args, fact if fact else f"Error: no fact named '{topic}'."
    if name == "lookup_workplace_knowledge":
        section = args.get("section")
        entries = knowledge_section(scenario["id"], section) if section in KNOWLEDGE_SECTIONS else None
        if entries is None:
            return args, f"Error: no section named '{section}'."
        payload = {"section": section, "basis": KNOWLEDGE["about"], "entries": entries}
        if config.compact_context():
            return args, json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        return args, json.dumps(payload, indent=1)
    if name == "get_workplace_guidance":
        entry = GUIDANCE.get(topic)
        if not entry:
            return args, f"Error: no guidance named '{topic}'."
        return args, entry["title"] + ":\n- " + "\n- ".join(entry["points"])
    return args, f"Error: tool '{name}' is not available."
