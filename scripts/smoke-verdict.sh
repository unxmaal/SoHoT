#!/usr/bin/env bash
# scripts/smoke.sh's exit: before the switch, a failure the serving release's own smoke does not share is this release's checks judging the old services, so it warns and the switch's smoke enforces it. #1790.
set -uo pipefail
rc="${1:-1}"
[ "$rc" -eq 0 ] && exit 0
[ "${SMOKE_PHASE:-}" = before ] || exit "$rc"
here="$(pwd -P)"
serving="${SMOKE_SERVING:-$(bash scripts/launchd.sh deploy-path 2>/dev/null)}"
serving="$(cd "$serving" 2>/dev/null && pwd -P)" || serving=""
if [ -z "$serving" ] || [ "$serving" = "$here" ] || [ ! -f "$serving/scripts/smoke.sh" ]; then
  exit "$rc"
fi
printf 'note  this release fails smoke before the switch; asking the serving release %s to judge its own services\n' "$serving"
SMOKE_PHASE=after bash "$serving/scripts/smoke.sh" 2>&1 | sed 's/^/serving  /'
if [ "${PIPESTATUS[0]}" -eq 0 ]; then
  printf "WARN  the serving release's own smoke passes, so the FAILs above are this release's checks against the services it replaces: enforced after the switch\n"
  exit 0
fi
printf "FAIL  the serving release's own smoke fails too: the services are broken before the switch\n"
exit "$rc"
