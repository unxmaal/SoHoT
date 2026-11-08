#!/usr/bin/env bash
# Runs a smoke check for a property this release introduces: it fails only when SMOKE_PHASE=after (the deploy switch sets it), else warns, since an older deploy may run this smoke against its own services. #1608.
set -uo pipefail
out="$("$@" 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && [ "${SMOKE_PHASE:-}" != after ]; then
  printf '%s\n' "$out" | sed 's/^FAIL /WARN /'
  printf 'WARN  enforced after the switch: the running services predate this check (rc %s)\n' "$rc"
  exit 0
fi
[ -z "$out" ] || printf '%s\n' "$out"
exit "$rc"
