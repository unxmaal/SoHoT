#!/usr/bin/env bash
# Tonight's discovery sweep, checked from launchd state and its heartbeat each hour 22:00..06:00, then exit. #1062.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== sweep-check $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
# After the header, so a refusal is logged under it. #1481.
source scripts/env.sh
exec uv run soh sweep-check --notify
