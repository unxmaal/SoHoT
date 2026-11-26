#!/usr/bin/env bash
# monit's gateway check (#2132): exit 1 while the gateway serves the base config with no sohot-<lane> aliases.
set -u
cd "$(dirname "$0")/.." || exit 1
exec uv run --quiet python -m harness.gateway_degraded check
