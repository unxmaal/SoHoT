#!/usr/bin/env bash
# One clip through a shot-boundary detector: the shots lane's transnetv2 and scenedetect engines (#1208).
#
# harness/engines.py builds the argv; this resolves the environment it runs in.
# See scripts/shots-venv.sh and harness/shot_detect.py.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/versions.sh

source scripts/shots-venv.sh

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

exec "$PY" -m harness.shot_detect "$@"
