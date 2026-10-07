#!/usr/bin/env bash
# antirez/ds4's ds4-server for the adopted ds4 spec, or $DS4_SPEC. #611.
# The argv comes from harness.ds4, the same code a measurement starts the server with.
# Exits 0 with nothing to serve, which launchd leaves stopped (KeepAlive SuccessfulExit=false).
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

LH_LOGS="${LOCALHARNESS_HOME:-$HOME/localharness}/logs"
mkdir -p "$LH_LOGS"

SPEC="${DS4_SPEC-}"
if [ -z "$SPEC" ] && [ -z "${DS4_SPEC+set}" ]; then
  SPEC="$(uv run python -m harness.ds4 adopted)"
fi
if [ -z "$SPEC" ]; then
  echo "ds4: nothing to serve (no lane has adopted a ds4: spec and DS4_SPEC is empty)"
  exit 0
fi

ARGS=()
while IFS= read -r line; do
  ARGS+=("$line")
done < <(uv run python -m harness.ds4 argv "$SPEC" --port "${DS4_PORT:-8087}" --pid "$$")
if [ ${#ARGS[@]} -eq 0 ]; then
  echo "FATAL: harness.ds4 could not build a launch for $SPEC" >&2
  exit 1
fi
if [ ! -x "${ARGS[0]}" ]; then
  echo "FATAL: ${ARGS[0]} is not built; run scripts/ds4-build.sh" >&2
  exit 1
fi
exec "${ARGS[@]}"
