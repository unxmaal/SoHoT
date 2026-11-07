#!/usr/bin/env bash
# The MCP port on both loopback stacks: a client whose localhost is ::1 is refused by an IPv4-only server. #1555.
set -uo pipefail
PORT="${1:-${MCP_PORT:-8899}}"
FAIL=0
for addr in 127.0.0.1 '[::1]'; do
  code="$(curl -gs -o /dev/null -w '%{http_code}' --max-time 5 "http://$addr:$PORT/mcp")"
  if [ "$code" = 000 ]; then
    printf 'FAIL  mcp at %s:%s refuses or never answers\n' "$addr" "$PORT"; FAIL=1
  else
    printf 'PASS  mcp at %s:%s (HTTP %s)\n' "$addr" "$PORT" "$code"
  fi
done
exit $FAIL
