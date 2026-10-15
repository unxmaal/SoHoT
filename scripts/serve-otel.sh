#!/usr/bin/env bash
# Claude Code's OpenTelemetry export, received on loopback into otel_metrics and otel_events. #868.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

exec uv run soh otel serve --host 127.0.0.1 --port "${OTEL_PORT:-4318}"
