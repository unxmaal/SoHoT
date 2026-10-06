#!/usr/bin/env bash
# The decide lane's nimble engine: one case through nimble's ParallelScorer.
#
# harness/engines.py builds the argv; this resolves the environment it runs in.
# See scripts/nimble-venv.sh and harness/nimble_score.py. #423.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
source scripts/versions.sh

source scripts/nimble-venv.sh

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

exec "$PY" -m harness.nimble_score "$@"
