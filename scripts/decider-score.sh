#!/usr/bin/env bash
# The decide lane's decider engine: one case through strands-decider.
#
# harness/engines.py builds the argv; this resolves the environment it runs in.
# See scripts/decider-venv.sh and harness/decider_score.py. #467.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
source scripts/versions.sh

source scripts/decider-venv.sh

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

exec "$PY" -m harness.decider_score "$@"
