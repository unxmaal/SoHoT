#!/usr/bin/env bash
# The weekly Claude Code changelog digest; a desktop notification only when an entry is relevant. #866.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== claude-news $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
# After the header, so a refusal is logged under it. #1481.
source scripts/env.sh
exec uv run soh claude-news --notify
