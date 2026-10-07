#!/usr/bin/env bash
# MLX inference engine. Serves any model in the local HF cache; the gateway
# decides which one by the `model` field it sends (mlx_lm.server hot-swaps
# per request, see PLAN.md).
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
LH_LOGS="${LOCALHARNESS_HOME:-$HOME/localharness}/logs"
mkdir -p "$LH_LOGS"
# Loopback only: it takes no key, so other machines reach it through the
# gateway, which does (#482). MLX_HOST overrides.
# mlx_lm.server behind a listen backlog of 256 rather than 5 (#542).
exec uv run python -m harness.mlx_server \
  --model "${BOOT_MODEL:-mlx-community/Qwen2.5-1.5B-Instruct-4bit}" \
  --host "${MLX_HOST:-127.0.0.1}" \
  --port "${MLX_PORT:-8081}"
