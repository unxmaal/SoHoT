#!/usr/bin/env bash
# The morning report, on a schedule: notifies only when something needs a person, then exits. #867.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

echo "=== morning $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exec uv run soh morning --notify
