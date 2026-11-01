#!/usr/bin/env bash
# The weekly planted-candidate canary, each plant under its own isolated LOCALHARNESS_HOME. #919.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== canary $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
# After the header, so a refusal is logged under it. #1481.
source scripts/env.sh
exec uv run soh canary --run
