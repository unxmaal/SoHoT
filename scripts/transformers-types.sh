#!/usr/bin/env bash
# Rewrite harness/transformers_model_types.txt from the hf-task venv's transformers (#567).
# Run after TRANSFORMERS_PIN moves; tests/test_remote_code.py fails until it is.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
source scripts/versions.sh
source scripts/hf-task-venv.sh

exec "$PY" -m harness.remote_code
