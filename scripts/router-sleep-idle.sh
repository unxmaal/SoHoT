#!/usr/bin/env bash
# Prints llama-server's --sleep-idle-seconds: never on a dedicated 64 GiB Mac, 300 on a desktop whose card has a day job (#694).
set -euo pipefail
bytes="${1:-}"
os="${2:-$(uname -s)}"
if [ -z "$bytes" ]; then
  bytes="$(sysctl -n hw.memsize 2>/dev/null || awk '/MemTotal/ {print $2 * 1024}' /proc/meminfo 2>/dev/null || echo 0)"
fi
if [ "$os" = Darwin ] && [ "${bytes:-0}" -ge $((64 * 1024 * 1024 * 1024)) ]; then echo -1; else echo "${LLAMACPP_SLEEP_IDLE:-300}"; fi
