#!/usr/bin/env bash
# The day fetch: downloads for the next night's screen, beside no sweep, rate-capped in the capped hours. #1084.
set -euo pipefail
cd "$(dirname "$0")/.."
GIB="${DAY_FETCH_GIB:-40}"
echo "=== day fetch $(date -u +%Y-%m-%dT%H:%M:%SZ) budget=${GIB}GiB ==="
# After the header, so a refusal is logged under it. #1481.
source scripts/env.sh
exec uv run soh fetch --day --budget-gib "$GIB"
