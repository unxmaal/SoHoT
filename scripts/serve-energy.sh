#!/usr/bin/env bash
# One macmon power reading into $LOCALHARNESS_HOME/ledger/power.jsonl, then exit. #826.
# Not a server: the plist carries StartInterval. Without macmon it says so and exits 0.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

if ! command -v macmon >/dev/null 2>&1; then
  echo "macmon not installed (brew install macmon): no energy reading"
  exit 0
fi
exec uv run soh ledger --sample-power
