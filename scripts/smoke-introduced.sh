#!/usr/bin/env bash
# Runs a smoke check for a property this release introduces: before the switch (SMOKE_PHASE=before) the old release's services answer, so a failure warns; after it, it fails. #1608.
set -uo pipefail
out="$("$@" 2>&1)"; rc=$?
if [ "$rc" -ne 0 ] && [ "${SMOKE_PHASE:-after}" = before ]; then
  printf '%s\n' "$out" | sed 's/^FAIL /WARN /'
  printf 'WARN  enforced after the switch: the running services predate this check (rc %s)\n' "$rc"
  exit 0
fi
[ -z "$out" ] || printf '%s\n' "$out"
exit "$rc"
