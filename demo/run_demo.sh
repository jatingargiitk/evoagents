#!/usr/bin/env bash
# Full EvoAgents demo: init → run → score → autofix (with guide) → rerun → inspect
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_DIR="${DEMO_DIR:-$ROOT_DIR/.demo-project}"
QUERY="${QUERY:-What are the most important AI developments in early 2026?}"
GUIDE="${GUIDE:-Always prefer primary sources over secondary. Cite publication dates.}"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "Error: OPENAI_API_KEY is not set." >&2
  exit 1
fi

if [[ -d "$DEMO_DIR" && -z "${RESET_DEMO:-}" ]]; then
  echo "Demo directory already exists: $DEMO_DIR" >&2
  echo "Set RESET_DEMO=1 to recreate it." >&2
  exit 1
fi

if [[ -d "$DEMO_DIR" && -n "${RESET_DEMO:-}" ]]; then
  rm -rf "$DEMO_DIR"
fi

echo "==> Installing EvoAgents..."
python -m pip install -e "$ROOT_DIR" -q

echo ""
echo "==> Initializing project from 'research' preset..."
evoagents init --preset research "$DEMO_DIR"
cd "$DEMO_DIR"

echo ""
echo "==> Run 1: baseline"
evoagents run "$QUERY"

echo ""
echo "==> Scoring run 1..."
evoagents score last

echo ""
echo "==> Failures in run 1..."
evoagents failures last

echo ""
echo "==> Running autofix with guiding principles..."
evoagents autofix last --guide "$GUIDE"

echo ""
echo "==> Run 2: after autofix"
evoagents run "$QUERY"

echo ""
echo "==> Scoring run 2..."
evoagents score last

echo ""
echo "==> Failures in run 2..."
evoagents failures last

echo ""
echo "==> Full trace of run 2..."
evoagents trace last

echo ""
echo "==> Skill versions (perception)..."
evoagents versions --skill perception

echo ""
echo "==> Diff v1 -> v2 (perception)..."
evoagents diff --skill perception v1 v2 || echo "(no v2 yet if autofix did not promote)"

echo ""
echo "Demo complete."
