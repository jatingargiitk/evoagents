# Demo

A full **run → score → autofix → rerun** loop using the `research` preset.

The research pipeline has three skills: `perception` (query understanding) →
`planner` (live web search via OpenAI Responses API) → `synthesizer` (structured
report). After a baseline run, `evoagents autofix` patches whichever skills failed,
replays on past traces to validate the patch, and promotes the winner automatically.

## Prerequisites

- Python 3.11+
- An OpenAI API key with access to `gpt-4o` or `gpt-5.2`

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install evoagents          # from PyPI
# or: pip install -e .         # from source
export OPENAI_API_KEY=sk-...
```

## Option A — Manual walkthrough (recommended for live demos)

```bash
# 1. Init a fresh project
evoagents init --preset research .demo-project
cd .demo-project

# 2. Baseline run
evoagents run "What are the most important AI developments in early 2026?"

# 3. Inspect results
evoagents score last
evoagents failures last

# 4. Autofix with your own guiding principles (optional but powerful)
evoagents autofix last --guide "Always prefer primary sources. Cite publication dates."

# 5. Run again — skills have evolved
evoagents run "What are the most important AI developments in early 2026?"
evoagents score last
evoagents failures last

# 6. Inspect the full trace
evoagents trace last

# 7. See what changed in each skill
evoagents versions --skill perception
evoagents diff --skill perception v1 v2

# 8. Create a new custom skill interactively
evoagents create-skill
```

## Option B — Scripted demo

```bash
# Basic
RESET_DEMO=1 ./demo/run_demo.sh

# Custom query + guiding principles
RESET_DEMO=1 \
QUERY="What are the latest breakthroughs in quantum computing?" \
GUIDE="Only cite peer-reviewed sources published in 2025 or 2026." \
./demo/run_demo.sh
```

## What to show during a demo

| Step | Command | What to highlight |
|------|---------|-------------------|
| Init | `evoagents init` | Skill files created from preset |
| Run | `evoagents run` | Live web search + structured JSON output |
| Score | `evoagents score last` | Per-skill scores, 0–1 |
| Failures | `evoagents failures last` | Exact failure tags the LLM judge identified |
| Autofix | `evoagents autofix last` | Patch generated, replayed on traces, promoted if score improves |
| Rerun | `evoagents run` | Same query, visibly improved output |
| Diff | `evoagents diff` | Exact line-level change the system made to the skill |

## Notes

- `evoagents trace last` shows every tool call, annotation URL, and step output —
  usually the best visual for a recording.
- To reset between runs: delete `.demo-project/.selfheal/` (keeps skills intact)
  or `rm -rf .demo-project` for a full reset.
- The `--guide` flag lets you inject principles that take highest priority over the
  default patcher behaviour — great for domain-specific guardrails.
