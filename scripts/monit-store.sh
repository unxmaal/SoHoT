#!/usr/bin/env bash
# monit's store checks (#1591): `check` exits 1 when the store's volume or container is gone; `backup` makes the daily dump.
set -u
cd "$(dirname "$0")/.." || exit 1
case "${1:-}" in
  check) exec uv run --quiet python -m harness.cli store pg-check ;;
  backup) exec uv run --quiet python -m harness.cli store pg-backup --due ;;
  *) echo "usage: monit-store.sh check|backup"; exit 2 ;;
esac
