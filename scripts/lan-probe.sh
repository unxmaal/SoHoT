#!/usr/bin/env bash
# Connects to each serving node from inside launchd, where macOS Local Network privacy applies. #739.
# Exit 1 when a node is blocked or the probe never ran; a down node is reported and passes.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
HERE="$PWD"
if [ "$(uname -s)" != Darwin ]; then
  echo "SKIP  LAN probe: Local Network privacy is macOS only"; exit 0
fi
DEPLOY="$(/bin/bash scripts/launchd.sh deploy-path)"
PY="${LAN_PROBE_PYTHON:-$DEPLOY/.venv/bin/python}"
if [ ! -x "$PY" ]; then
  echo "SKIP  LAN probe: no gateway python at $PY"; exit 0
fi
TARGETS="$(uv run python -m harness.lanprobe targets)" || { echo "FAIL  LAN probe: cannot read the node list"; exit 1; }
if [ -z "$TARGETS" ]; then
  echo "SKIP  LAN probe: no serving nodes"; exit 0
fi
WAIT_EXTRA="${LAN_PROBE_WAIT_EXTRA_S:-5}"
FAIL=0
while read -r name host port timeout ipv4; do
  label="com.unxmaal.localharness.lanprobe.$$.$name"
  out="$(mktemp "${TMPDIR:-/tmp}/lanprobe.XXXXXX")"
  launchctl submit -l "$label" -o "$out" -e "$out" -- \
    "$PY" -I "$HERE/harness/lanprobe.py" connect "$host" "$port" "$timeout" "$ipv4" </dev/null
  # A submitted job is kept alive, so read its first line and remove it; the label is per run.
  deadline=$(( $(date +%s) + ${timeout%.*} + WAIT_EXTRA ))
  while [ ! -s "$out" ] && [ "$(date +%s)" -le "$deadline" ]; do sleep 0.2; done
  launchctl remove "$label" || echo "warning: launchd job $label is still loaded; run: launchctl remove $label" >&2
  uv run python -m harness.lanprobe verdict "$name" "$host:$port" "$out" "$PY" </dev/null || FAIL=1
  rm -f "$out"
done <<<"$TARGETS"
exit $FAIL
