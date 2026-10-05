"""
Partner Solution Triage Agent
-----------------------------
A multi-step agent that takes a partner-submitted customer use case and works
through it using tools before producing a structured recommendation.

This is deliberately partner-shaped: it is the kind of triage a GSI technical
lead does by hand today, and the kind of thing a Partner Solutions Architect
would prototype to show a partner what "agentic" actually means in practice.

Run:  python agent.py "customer use case text here"
      python agent.py            # uses a built-in example
"""

import json
import os
import sys

from anthropic import Anthropic
from dotenv import load_dotenv

MODEL = "claude-sonnet-5-5"
MAX_TURNS = 8

# Reads ANTHROPIC_API_KEY from agent/.env (git-ignored) if it is not already set.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ---------------------------------------------------------------------------
# Tools: these are the "hands" of the agent. Each one is a plain Python
# function. The model decides when to call them and with what arguments.
# ---------------------------------------------------------------------------

with open(os.path.join(os.path.dirname(__file__), "patterns.json")) as f:
    PATTERNS = json.load(f)


def search_reference_patterns(query: str) -> str:
    """Naive keyword search over a small library of deployment patterns."""
    terms = {t for t in query.lower().split() if len(t) > 3}
    scored = []
    for p in PATTERNS:
        haystack = (p["name"] + " " + p["summary"] + " " + " ".join(p["tags"])).lower()
        score = sum(1 for t in terms if t in haystack)
        if score:
            scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    hits = [p for _, p in scored[:3]]
    if not hits:
        return "No matching patterns found."
    return json.dumps(hits, indent=2)


def check_data_readiness(data_sources: list) -> str:
    """Return a readiness checklist for the named data sources."""
    checklist = []
    for src in data_sources:
        checklist.append(
            {
                "source": src,
                "questions": [
                    "Is there a single owner accountable for this data?",
                    "Is access governed by an existing policy, or ad hoc?",
                    "Is it structured, semi-structured, or unstructured?",
                    "How stale is it at the point of retrieval?",
                    "Does it contain PII or regulated content?",
                ],
                "blocks_deployment_if": "no owner, or ungoverned access to regulated content",
            }
        )
    return json.dumps(checklist, indent=2)


def estimate_complexity(agent_steps: int, integrations: int, human_in_loop: bool) -> str:
    """Crude complexity scoring, to force the model to commit to a number."""
    score = agent_steps * 2 + integrations * 3 + (0 if human_in_loop else 4)
    if score <= 8:
        band = "low - single agent, prompt + tools, weeks to pilot"
    elif score <= 16:
        band = "medium - orchestrated multi-step, needs eval harness, months to pilot"
    else:
        band = "high - multi-agent or long-horizon, needs eval + monitoring + rollback"
    return json.dumps({"score": score, "band": band})


TOOLS = [
    {
        "name": "search_reference_patterns",
        "description": "Search the library of known enterprise deployment patterns. Use this before recommending an architecture.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords describing the use case"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "check_data_readiness",
        "description": "Get a data readiness checklist for the data sources this use case depends on.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data_sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Named systems or data sources, e.g. 'Salesforce CRM', 'SharePoint'",
                }
            },
            "required": ["data_sources"],
        },
    },
    {
        "name": "estimate_complexity",
        "description": "Score the deployment complexity of the proposed solution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_steps": {"type": "integer"},
                "integrations": {"type": "integer"},
                "human_in_loop": {"type": "boolean"},
            },
            "required": ["agent_steps", "integrations", "human_in_loop"],
        },
    },
]

DISPATCH = {
    "search_reference_patterns": search_reference_patterns,
    "check_data_readiness": check_data_readiness,
    "estimate_complexity": estimate_complexity,
}


SYSTEM = """You are a partner solutions architect triaging a customer use case
submitted by a systems integrator.

Work through the problem using your tools before you answer. You must:
1. Search reference patterns before recommending an architecture.
2. Check data readiness for every data source the use case depends on.
3. Estimate complexity once you have settled on a shape.

Then produce your final answer as a JSON object ONLY, no prose around it, with keys:
  "recommended_pattern": string
  "why": string (two sentences max)
  "data_risks": array of strings
  "complexity_band": string
  "biggest_unknown": string - the single question that most needs answering before pilot

If the use case is too vague to triage, set "recommended_pattern" to "INSUFFICIENT_INFO"
and put the missing information in "biggest_unknown"."""


def run(use_case: str, verbose: bool = True) -> str:
    messages = [{"role": "user", "content": use_case}]

    for turn in range(MAX_TURNS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            if verbose:
                print(f"\n--- finished after {turn + 1} turns ---\n")
            return text

        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            if verbose:
                print(f"[turn {turn + 1}] calling {block.name}({json.dumps(block.input)[:120]})")
            try:
                out = DISPATCH[block.name](**block.input)
            except Exception as e:
                # Tool errors are fed back to the model rather than crashing.
                out = f"ERROR: {e}"
            results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": out}
            )

        messages.append({"role": "user", "content": results})

    return '{"error": "hit MAX_TURNS without a final answer"}'


EXAMPLE = """Client is an Australian general insurer. They want to cut claims
handling time. Today an assessor reads the claim form, pulls the policy from
the policy admin system, checks prior claims history, and writes a liability
assessment. About 400 claims a day. They want AI to draft the assessment.
Data sits in Guidewire, a SharePoint document store, and a legacy claims
history database. They have asked us about "agents"."""


if __name__ == "__main__":
    use_case = sys.argv[1] if len(sys.argv) > 1 else EXAMPLE
    print(run(use_case))
