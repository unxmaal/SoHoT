#!/usr/bin/env bash
# The weekly adversarial review; it files only when LH_REVIEW_FILE=1 is in the environment too. #1149.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

echo "=== review $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exec uv run soh review run --file
