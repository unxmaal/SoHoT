#!/usr/bin/env bash
# The sweep, on a schedule. Issue #261.
#
# THIS IS THE PRODUCT'S PREMISE. Obsoletion-proofing that has to be typed by a
# person is a script, not a property of the system: the loop turns only when
# somebody remembers, and what it is meant to protect against is precisely the
# passage of unattended time.
#
# NOT A SERVER, despite living beside the serve-* scripts. launchd runs it at
# fixed hours and it exits; the plist carries StartCalendarInterval rather than
# KeepAlive, or launchd would restart a finished sweep immediately. #625.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

LH_LOGS="${LOCALHARNESS_HOME:-$HOME/localharness}/logs"
mkdir -p "$LH_LOGS"

# WHAT AN UNATTENDED RUN MAY SPEND. A scheduled job that downloads without a
# ceiling fills the disk overnight and is discovered the next morning; the loop
# already refuses to exceed these and they are here so the answer is visible in
# the place that sets the schedule.
# 0: the sweep ceiling sizes the fetch, screen and measure; a count overrides it. #1084.
TOP="${DISCOVER_TOP:-0}"
BUDGET="${DISCOVER_BUDGET_GIB:-40}"
# Unset, the loop's power plan picks the repeat per lane within its time budget (#479, #591, #696).
REPEAT="${DISCOVER_REPEAT:-}"

echo "=== sweep $(date -u +%Y-%m-%dT%H:%M:%SZ) top=${TOP/#0/ceiling} budget=${BUDGET}GiB ==="
# Not exec: a sweep killed by a bootout or ^C must leave a line in discover.log. #794.
child=""
_killed() {
  echo "=== sweep killed by SIG$1 $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >&2
  [ -z "$child" ] || kill -s TERM -- "-$child" 2>/dev/null || exit "$2"
  wait "$child" 2>/dev/null || exit "$2"
  exit "$2"
}
trap '_killed TERM 143' TERM
trap '_killed INT 130' INT
trap '_killed HUP 129' HUP
# Its own process group, so the trap reaches every descendant, not just uv. #805.
set -m
[ "$TOP" = 0 ] && TOP=""
uv run soh discover --loop --run \
  ${TOP:+--top "$TOP"} --budget-gib "$BUDGET" ${REPEAT:+--repeat "$REPEAT"} &
child=$!
wait "$child"
