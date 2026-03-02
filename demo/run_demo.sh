#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_DIR="${DEMO_DIR:-$ROOT_DIR/.demo-project}"
QUERY="${QUERY:-What were the key AI breakthroughs in 2025?}"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is not set." >&2
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

python -m pip install -e "$ROOT_DIR"

evoagents init --preset research "$DEMO_DIR"
cd "$DEMO_DIR"

evoagents run "$QUERY"
evoagents score last
evoagents failures last

evoagents autofix last

evoagents run "$QUERY"
evoagents score last
evoagents failures last

evoagents trace last
