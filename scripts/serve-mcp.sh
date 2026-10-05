#!/usr/bin/env bash
# localharness over MCP, so another machine's agent can use this one's GPU.
#
# svg, web and code answer directly; image and video go on the work queue that
# serve-worker.sh runs (#353). Speech over the LAN was ruled out.
#
# Binds every interface by default, like the other services and for the same
# reason: on a trusted LAN the models are local, and the point of the machine
# is that other machines on it can use the GPU. There is NO
# AUTHENTICATION -- set MCP_HOST=127.0.0.1 on an untrusted network.
#
# The client entry, on the other machine:
#   claude mcp add --transport http localharness http://<host>.local:8899/mcp
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
LH_LOGS="${LOCALHARNESS_HOME:-$HOME/localharness}/logs"
mkdir -p "$LH_LOGS"

HOST="${MCP_HOST:-0.0.0.0}"
PORT="${MCP_PORT:-8899}"
echo "mcp   http://$(scutil --get LocalHostName 2>/dev/null || hostname).local:$PORT/mcp" >&2
exec uv run --group mcp python -m harness.mcp_server \
  --host "$HOST" --port "$PORT" --transport streamable-http \
  ${MCP_ALLOW:+--allow "$MCP_ALLOW"}
