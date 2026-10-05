#!/usr/bin/env bash
# The work queue's worker: runs queued jobs in order while nobody is using this
# machine. See harness/workqueue.py and harness/presence.py. #353.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
LH_LOGS="${LOCALHARNESS_HOME:-$HOME/localharness}/logs"
mkdir -p "$LH_LOGS"
exec uv run python -u -m harness.workqueue
