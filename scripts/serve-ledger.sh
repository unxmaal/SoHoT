#!/usr/bin/env bash
# The ledger's daily rows: today and yesterday upserted into ledger_days, then exit. #826.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== ledger $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
# After the header, so a refusal is logged under it. #1481.
source scripts/env.sh
exec uv run soh ledger --since 2d --record
