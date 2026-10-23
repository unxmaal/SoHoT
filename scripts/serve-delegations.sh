#!/usr/bin/env bash
# Pending delegation outcomes closed from the callers' transcripts, or expired to unknown, then exit. #1158.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

echo "=== delegations $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exec uv run soh delegated --close
