"""
Eval harness for the triage agent.

This is the part worth building. Anyone can get an agent to work once.
The question that separates a demo from a deployment is: how do you know
it still works tomorrow, on an input you have not seen?

Run:  python evals.py
      python evals.py --runs 3     # same cases, repeated, to see variance
"""

import argparse
import json
from collections import defaultdict

from agent import run

# Each case has a use case, the pattern(s) a competent architect would accept,
# and anything the output must mention. Deliberately includes a vague case
# that the agent SHOULD refuse to triage.
CASES = [
    {
        "id": "claims-drafting",
        "use_case": (
            "Australian insurer wants AI to draft liability assessments for motor claims. "
            "400 claims a day. Assessor reads the claim, pulls policy from Guidewire, "
            "checks prior claims history, writes the assessment. Human signs off today."
        ),
        "acceptable_patterns": [
            "Retrieval-grounded drafting",
            "Human-in-the-loop approval gate",
            "Orchestrated multi-step with tool use",
        ],
        "must_mention": ["guidewire"],
    },
    {
        "id": "support-triage",
        "use_case": (
            "Telco wants to reduce time-to-first-response in support. 12,000 tickets a week "
            "arriving by email and webform, wildly variable quality. Most are password resets "
            "and billing queries, but a long tail of genuine faults needs engineers."
        ),
        "acceptable_patterns": ["Classify then route"],
        "must_mention": [],
    },
    {
        "id": "doc-backlog",
        "use_case": (
            "Mining company has 90,000 scanned contractor safety certificates in SharePoint. "
            "They need expiry date, contractor name and certificate type extracted into their "
            "compliance system. No urgency on latency. Audit is in six months."
        ),
        "acceptable_patterns": ["Batch enrichment"],
        "must_mention": ["sharepoint"],
    },
    {
        "id": "too-vague",
        "use_case": "A bank wants to use agents to transform customer experience.",
        "acceptable_patterns": ["INSUFFICIENT_INFO"],
        "must_mention": [],
    },
]


def parse(raw: str):
    """The model is asked for JSON only. It does not always comply."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def grade(case, raw):
    result = {"id": case["id"], "parsed": False, "pattern_ok": False, "mentions_ok": False}
    try:
        out = parse(raw)
    except Exception as e:
        result["error"] = f"unparseable JSON: {e}"
        return result

    result["parsed"] = True
    result["pattern"] = out.get("recommended_pattern", "")
    result["pattern_ok"] = any(
        p.lower() in result["pattern"].lower() for p in case["acceptable_patterns"]
    )

    blob = json.dumps(out).lower()
    missing = [m for m in case["must_mention"] if m not in blob]
    result["mentions_ok"] = not missing
    if missing:
        result["missing"] = missing

    for key in ["why", "data_risks", "complexity_band", "biggest_unknown"]:
        if key not in out:
            result.setdefault("schema_gaps", []).append(key)

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    args = ap.parse_args()

    tally = defaultdict(list)

    for r in range(args.runs):
        print(f"\n{'=' * 60}\nRUN {r + 1}\n{'=' * 60}")
        for case in CASES:
            raw = run(case["use_case"], verbose=False)
            res = grade(case, raw)
            tally[case["id"]].append(res)

            flags = []
            if not res["parsed"]:
                flags.append("UNPARSEABLE")
            else:
                if not res["pattern_ok"]:
                    flags.append(f"WRONG PATTERN -> {res['pattern']}")
                if not res["mentions_ok"]:
                    flags.append(f"MISSED {res['missing']}")
                if res.get("schema_gaps"):
                    flags.append(f"SCHEMA GAPS {res['schema_gaps']}")

            status = "PASS" if not flags else "FAIL"
            print(f"  [{status}] {case['id']:<16} {'; '.join(flags)}")

    print(f"\n{'=' * 60}\nSUMMARY\n{'=' * 60}")
    for cid, runs in tally.items():
        passes = sum(
            1 for r in runs if r["parsed"] and r["pattern_ok"] and r["mentions_ok"]
        )
        print(f"  {cid:<16} {passes}/{len(runs)} passed")


if __name__ == "__main__":
    main()
