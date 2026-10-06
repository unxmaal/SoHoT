#!/usr/bin/env bash
# Fetch one GGUF file into the flat directory llama-server's router reads, and
# record it in the store's downloads table (#411).
#
#   ./scripts/fetch-gguf.sh unsloth/Qwen3-4B-Instruct-2507-GGUF Qwen3-4B-Instruct-2507-Q4_K_M.gguf
#
# The router serves a file under its stem, so the gateway alias names the stem.
# harness.gguf restarts the eval server so the router sees the file (#319).
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
[ $# -eq 2 ] || { echo "usage: $0 REPO FILE.gguf" >&2; exit 2; }
HF_HUB_OFFLINE=0 uv run --with huggingface_hub python -m harness.gguf "$1" "$2"
