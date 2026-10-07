#!/usr/bin/env bash
# One case through transformers: the ocr lane's hf-ocr engine (#562).
#
# harness/engines.py builds the argv; this resolves the environment it runs in.
# See scripts/hf-task-venv.sh and harness/hf_task.py.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
source scripts/versions.sh

source scripts/hf-task-venv.sh

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

exec "$PY" -m harness.hf_task "$@"
