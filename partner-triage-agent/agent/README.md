# Partner Solution Triage Agent

A multi-step agent built on the Claude API. It takes a customer use case submitted
by a systems integrator, works through it using tools, and returns a structured
triage: recommended pattern, data risks, complexity band, and the biggest unknown.

Built to pressure-test the deployment patterns I advise partners on — and to find
out where they break.

## Setup

```bash
pip install -r requirements.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env   # from console.anthropic.com; .env is git-ignored
python agent.py                          # runs the built-in insurance example
python agent.py "your own use case here"
python evals.py --runs 3                 # the part that actually matters
```

## What's here

- `agent.py` — the agent loop. Three tools, max 8 turns, structured JSON output.
- `patterns.json` — a small library of enterprise deployment patterns, each with
  a `fails_when` field. The failure modes are the useful part.
- `evals.py` — four test cases with graded output, including one deliberately
  vague case the agent is supposed to *refuse* to triage.

## The design decisions worth defending

**One agent with tools, not multiple agents.** Multi-agent is in the pattern
library but the triage task doesn't need it. Reaching for multi-agent before
a single orchestrated loop has failed is the most common mistake I see partners
make.

**Tool errors are returned to the model, not raised.** A tool that throws kills
the run. A tool that returns `ERROR: ...` lets the model recover or report
honestly. In production that difference is most of your reliability.

**`MAX_TURNS` exists because agents don't always know when to stop.** The loop
terminating is a design decision, not a given.

**The eval harness has a negative case.** "A bank wants to use agents to transform
customer experience" should return `INSUFFICIENT_INFO`. An agent that confidently
triages a non-brief is worse than one that refuses, and most demos never test this.

**`--runs 3` is there because the same input doesn't give the same output.**
Variance across identical runs is the thing enterprises are least prepared for,
and the reason "it worked when I demoed it" is not evidence of anything.

## Things to watch for when you run it

Keep notes on these — they are the real content.

1. Does it call the tools in the order the system prompt asks for, every time?
2. Does it ever skip `check_data_readiness` when the use case names obvious systems?
3. On `--runs 3`, does the same case get the same pattern each time?
4. Does it wrap the JSON in markdown fences despite being told not to?
5. On the vague bank case, does it refuse — or does it invent a plausible brief?

Number 5 is the one worth having an opinion about.
