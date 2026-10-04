#!/usr/bin/env bash
# Fetch one GGUF file into the flat directory llama-server's router reads.
#
#   ./scripts/fetch-gguf.sh unsloth/Qwen3-4B-Instruct-2507-GGUF Qwen3-4B-Instruct-2507-Q4_K_M.gguf
#
# The router serves a file under its stem, so the gateway alias names the stem.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
[ $# -eq 2 ] || { echo "usage: $0 REPO FILE.gguf" >&2; exit 2; }
mkdir -p "$HF_HOME/gguf"
HF_HUB_OFFLINE=0 uv run --no-project --with huggingface_hub \
  hf download "$1" "$2" --local-dir "$HF_HOME/gguf"
# The router reads its directory at startup only (#319).
[ "$(uname)" = Darwin ] && scripts/launchd.sh restart eval
echo "$HF_HOME/gguf/$2"
