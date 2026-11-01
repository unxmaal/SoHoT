#!/usr/bin/env bash
# The morning report, on a schedule: notifies only when something needs a person, then exits. #867.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== morning $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
# After the header, so a refusal is logged under it. #1481.
source scripts/env.sh
exec uv run soh morning --notify
