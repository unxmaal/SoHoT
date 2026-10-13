#!/usr/bin/env bash
# The ledger's daily rows: today and yesterday upserted into ledger_days, then exit. #826.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

echo "=== ledger $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exec uv run soh ledger --since 2d --record
