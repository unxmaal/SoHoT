#!/usr/bin/env bash
# The MCP port on both loopback stacks: a client whose localhost is ::1 is refused by an IPv4-only server. #1555.
set -uo pipefail
PORT="${MCP_PORT:-8899}"
case "${1:-}" in ''|*[!0-9]*) ;; *) PORT="$1"; shift ;; esac
if [ $# -gt 0 ]; then ADDRS=("$@"); else ADDRS=(127.0.0.1 '[::1]'); fi
FAIL=0
for addr in "${ADDRS[@]}"; do
  code="$(curl -gs -o /dev/null -w '%{http_code}' --max-time 5 "http://$addr:$PORT/mcp")"
  if [ "$code" = 000 ]; then
    printf 'FAIL  mcp at %s:%s refuses or never answers\n' "$addr" "$PORT"; FAIL=1
  else
    printf 'PASS  mcp at %s:%s (HTTP %s)\n' "$addr" "$PORT" "$code"
  fi
done
exit $FAIL
