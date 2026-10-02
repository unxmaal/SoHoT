#!/usr/bin/env bash
# llama-server beside mlx_lm.server, for clients that need schema-valid JSON:
# mlx_lm.server ignores response_format, llama-server enforces it. #286.
set -euo pipefail
cd "$(dirname "$0")/.."
export LLAMACPP_PORT="${LLAMACPP_PORT:-8082}"
exec scripts/serve-llamacpp.sh
