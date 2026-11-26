#!/usr/bin/env bash
# monit's Needs-you pass (#2134): alert each stopped condition once as it begins and once as it clears; exit 1 only when it cannot read the status.
set -u
cd "$(dirname "$0")/.." || exit 1
exec uv run --quiet soh needs-you --alert
