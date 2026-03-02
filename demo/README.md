# Demo

This demo walks through a full run -> score -> autofix -> rerun loop using the
`research` preset. It is optimized for a live walkthrough.

## Prereqs

- Python 3.11+
- An OpenAI API key with access to the Responses API

## Setup

From the repo root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
export OPENAI_API_KEY=sk-...
```

## Run the demo

### Option A: Manual walkthrough (best for live demos)

```bash
evoagents init --preset research .demo-project
cd .demo-project

evoagents run "What were the key AI breakthroughs in 2025?"
evoagents score last
evoagents failures last

evoagents autofix last

evoagents run "What were the key AI breakthroughs in 2025?"
evoagents score last
evoagents failures last

evoagents trace last
```

### Option B: Scripted demo

```bash
DEMO_DIR=.demo-project \
QUERY="What were the key AI breakthroughs in 2025?" \
./demo/run_demo.sh
```

## Notes

- `evoagents trace last` is usually the best visual for a demo. It shows tool calls,
  evidence entries, and the full step outputs.
- If you want a fresh run each time, delete `.demo-project/.selfheal/` or set
  `RESET_DEMO=1` when running the script.
