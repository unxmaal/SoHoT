#!/usr/bin/env bash
# The watchdog, on a schedule: one wake, then exit. #814.
# Not a server: the plist carries StartCalendarInterval. It acts only when LH_WATCHDOG_ACT=1.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== watchdog $(date -u +%Y-%m-%dT%H:%M:%SZ) act=${LH_WATCHDOG_ACT:-dry-run} ==="
# After the header, so a refusal is logged under it. #1481.
source scripts/env.sh
exec uv run soh watchdog
