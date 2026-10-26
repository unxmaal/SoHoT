#!/usr/bin/env bash
# The vision lane's mlx-vlm labeller: every frame through one loaded model (#1282).
#
# harness/commands/vision.py builds the argv; this resolves the environment it runs in.
# See scripts/mlx-vlm-venv.sh and harness/mlx_vlm_label.py.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
source scripts/versions.sh

source scripts/mlx-vlm-venv.sh

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

exec "$PY" -m harness.mlx_vlm_label "$@"
