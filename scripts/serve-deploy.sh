#!/usr/bin/env bash
# Queue a deploy job for a new green origin/main commit, then exit; the job waits for its day window. #1506.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== deploy poll $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
# After the header, so a refusal is logged under it. #1481.
source scripts/env.sh
exec uv run soh deploy poll
