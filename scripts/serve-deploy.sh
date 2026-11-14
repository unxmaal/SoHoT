#!/usr/bin/env bash
# Queue a deploy job for a new green origin/main commit, then exit; the job waits for its day window. #1506.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== deploy poll $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
# A weights root env.sh refuses holds deploys; the poll says so once per cause and alerts, not a FATAL a minute. #1481, #2011.
if (source scripts/env.sh) >/dev/null 2>&1; then
  source scripts/env.sh
fi
exec uv run soh deploy poll
