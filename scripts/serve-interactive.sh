#!/usr/bin/env bash
# The interactive server: a llama-server holding each LAN lane's model pinned, which evals never load into. #1561.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
LH_HOME="${LOCALHARNESS_HOME:-$HOME/localharness}"
export LLAMACPP_PORT="${INTERACTIVE_PORT:-8083}"
export LLAMACPP_PRESET="$LH_HOME/interactive-preset-$LLAMACPP_PORT.ini"
# Refuses, naming the overrun, when the pinned set does not fit beside the largest eval pair.
MODELS="$(uv run python -m harness.interactive serve "$LLAMACPP_PRESET")"
if [ -z "$MODELS" ]; then
  echo "interactive: no pinned lane has a GGUF here; nothing to serve" >&2
  exit 0
fi
# Only the pinned files are in its models dir, its models-max holds them all, and it never sleeps.
export LLAMACPP_MODELS_DIR="$MODELS" LLAMACPP_SLEEP_IDLE=-1
uv run python -m harness.interactive warm &
exec scripts/serve-llamacpp.sh
