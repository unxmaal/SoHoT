#!/usr/bin/env bash
# monit's queue check (#2064): exit 1 when no job started or finished for queue_stale_alert while a due job waits.
set -u
cd "$(dirname "$0")/.." || exit 1
exec uv run --quiet python -m harness.queue_stale
