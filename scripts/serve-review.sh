#!/usr/bin/env bash
# The weekly adversarial review; it files only when LH_REVIEW_FILE=1 is in the environment too. #1149.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== review $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
# After the header, so a refusal is logged under it. #1481.
source scripts/env.sh
exec uv run soh review run --file
