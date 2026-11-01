#!/usr/bin/env bash
# monit's memory check (#1485): exit 1 while macOS memory pressure is past normal (harness/pressure.py NORMAL).
set -uo pipefail
level="$(sysctl -n kern.memorystatus_vm_pressure_level 2>/dev/null)" || level=""
case "$level" in
  ''|*[!0-9]*) echo "memory pressure unknown"; exit 0 ;;
esac
if [ "$level" -gt 1 ]; then
  echo "memory pressure level $level (1 normal, 2 warn, 4 critical)"
  exit 1
fi
echo "memory pressure level $level"
