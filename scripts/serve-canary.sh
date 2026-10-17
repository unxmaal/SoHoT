#!/usr/bin/env bash
# The weekly planted-candidate canary, each plant under its own isolated LOCALHARNESS_HOME. #919.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

echo "=== canary $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exec uv run soh canary --run
