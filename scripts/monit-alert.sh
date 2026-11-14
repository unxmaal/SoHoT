#!/usr/bin/env bash
# monit's exec action (#1485): `soh monitor alert KIND` with monit's MONIT_* variables; a desktop notice if that fails.
set -u
cd "$(dirname "$0")/.." || exit 1
LH_HOME="${LOCALHARNESS_HOME:-$HOME/localharness}"
LOG="$LH_HOME/logs/monit-alert.log"
mkdir -p "$(dirname "$LOG")"
echo "=== monit-alert ${1:-} ${MONIT_SERVICE:-} $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG"
uv run --quiet python -m harness.cli monitor alert "${1:-}" >> "$LOG" 2>&1
rc=$?
[ "$rc" -eq 0 ] && exit 0
# Only a home known not to be the live one stays off the desktop; a gate that cannot run still notifies. #2008.
python3 -I harness/live_gate.py "$LH_HOME" "monit-alert.sh's desktop notice" >> "$LOG" 2>&1
[ "$?" -eq 3 ] && exit "$rc"
osascript -e 'on run argv' -e 'display notification (item 2 of argv) with title (item 1 of argv)' -e 'end run' \
  "SoHoT monit" "${1:-}: ${MONIT_SERVICE:-}: ${MONIT_DESCRIPTION:-} (alert action rc $rc)" >/dev/null 2>&1
exit "$rc"
