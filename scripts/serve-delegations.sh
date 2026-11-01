#!/usr/bin/env bash
# Pending delegation outcomes closed from the callers' transcripts, or expired to unknown, then exit. #1158.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== delegations $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
# After the header, so a refusal is logged under it. #1481.
source scripts/env.sh
exec uv run soh delegated --close
