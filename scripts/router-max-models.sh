#!/usr/bin/env bash
# Prints how many models llama-server's router may hold on this machine's memory (#644).
set -euo pipefail
bytes="${1:-}"
if [ -z "$bytes" ]; then
  bytes="$(sysctl -n hw.memsize 2>/dev/null || awk '/MemTotal/ {print $2 * 1024}' /proc/meminfo 2>/dev/null || echo 0)"
fi
if [ "${bytes:-0}" -ge $((64 * 1024 * 1024 * 1024)) ]; then echo 2; else echo 1; fi
