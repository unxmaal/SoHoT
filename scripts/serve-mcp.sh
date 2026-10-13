#!/usr/bin/env bash
# localharness over MCP, so another machine's agent can use this one's GPU.
#
# svg, web and code answer directly; image and video go on the work queue that
# serve-worker.sh runs (#353). Speech over the LAN was ruled out.
#
# Binds 127.0.0.1 by default. MCP_HOST=0.0.0.0 opens it to the LAN, and then every
# request must carry the gateway key (#510):
#   claude mcp add --transport http soh http://<host>.local:8899/mcp \
#     --header "Authorization: Bearer <the key from soh gateway key>"
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
LH_LOGS="${LOCALHARNESS_HOME:-$HOME/localharness}/logs"
mkdir -p "$LH_LOGS"

HOST="${MCP_HOST:-127.0.0.1}"
PORT="${MCP_PORT:-8899}"
echo "mcp   http://$HOST:$PORT/mcp" >&2
exec uv run --group mcp python -m harness.mcp_server \
  --host "$HOST" --port "$PORT" --transport streamable-http \
  ${MCP_ALLOW:+--allow "$MCP_ALLOW"}
