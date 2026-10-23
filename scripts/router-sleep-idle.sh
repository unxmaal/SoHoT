#!/usr/bin/env bash
# Prints llama-server's --sleep-idle-seconds: on a Mac it outlasts a paired turn and its watchdog gives back sooner by day; elsewhere nothing else does (#1157).
set -euo pipefail
os="${1:-$(uname -s)}"
if [ "$os" = Darwin ]; then echo "${SERVE_IDLE_UNLOAD_S:-3600}"; else echo "${LLAMACPP_SLEEP_IDLE:-300}"; fi
