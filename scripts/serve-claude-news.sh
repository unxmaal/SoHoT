#!/usr/bin/env bash
# The weekly Claude Code changelog digest; a desktop notification only when an entry is relevant. #866.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

echo "=== claude-news $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exec uv run soh claude-news --notify
