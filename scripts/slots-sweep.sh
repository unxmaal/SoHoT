#!/bin/bash
# Throughput at several slot counts on a scratch llama-server router, never the live one. #665, #682.
# Usage: scripts/slots-sweep.sh STEM SLOT_CTX "SLOTS:POOL_SLOTS:unified|split:LEVEL ..." [soh throughput args...]
# Env: SWEEP_PORT (18682), SWEEP_SECOND (a stem kept resident beside STEM), SWEEP_BUDGET_S (no config starts past it),
#      SWEEP_LONG (tokens for a one-request long-context probe per multi-slot config, 0 = none), SWEEP_OUT.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
STEM="$1"; SLOT_CTX="$2"; CONFIGS="$3"; shift 3
PORT="${SWEEP_PORT:-18682}"
SECOND="${SWEEP_SECOND:-}"
BUDGET="${SWEEP_BUDGET_S:-2100}"
LONG="${SWEEP_LONG:-0}"
OUT="${SWEEP_OUT:-$(mktemp -d)}"
MODELS_SRC="${LLAMACPP_MODELS_DIR:-$HF_HOME/gguf}"
mkdir -p "$OUT/models"
for s in "$STEM" ${SECOND:+"$SECOND"}; do
  ln -sf "$MODELS_SRC/$s.gguf" "$OUT/models/$s.gguf"
done
START=$(date +%s)
SERVER=""
stop() {
  if [ -n "$SERVER" ] && kill "$SERVER" 2>/dev/null; then
    wait "$SERVER" 2>/dev/null || echo "== router $SERVER stopped ($?)"
  fi
  SERVER=""
}
trap stop EXIT

for cfg in $CONFIGS; do
  IFS=: read -r slots pool mode level <<<"$cfg"
  if [ $(( $(date +%s) - START )) -gt "$BUDGET" ]; then
    echo "== $cfg skipped: past the ${BUDGET}s budget"; continue
  fi
  ini="$OUT/preset-$slots-$pool-$mode.ini"
  {
    echo "version = 1"; echo; echo "[*]"; echo "c = 16384"; echo "parallel = 1"; echo
    echo "[$STEM]"; echo "c = $(( pool * SLOT_CTX ))"; echo "parallel = $slots"; echo "verbose = 1"
    if [ "$mode" = unified ]; then echo "kv-unified = true"; else echo "kv-unified = false"; fi
  } >"$ini"
  log="$OUT/server-$slots-$pool-$mode.log"
  llama-server --jinja --models-dir "$OUT/models" --models-preset "$ini" --models-max 2 \
    --sleep-idle-seconds 3600 --n-gpu-layers 999 --host 127.0.0.1 --port "$PORT" >"$log" 2>&1 &
  SERVER=$!
  up=""
  for _ in $(seq 1 120); do
    if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; then up=1; break; fi
    sleep 1
  done
  if [ -z "$up" ]; then echo "== $cfg skipped: router did not come up (see $log)"; stop; continue; fi
  if [ -n "$SECOND" ]; then
    curl -sf -m 300 "http://127.0.0.1:$PORT/v1/chat/completions" -H 'Content-Type: application/json' \
      -d "{\"model\":\"$SECOND\",\"max_tokens\":8,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}" >/dev/null \
      || echo "== $cfg: second model $SECOND did not answer"
  fi
  echo "== $cfg: $slots slots, pool $(( pool * SLOT_CTX )) tokens, $mode, $level in flight, second ${SECOND:-none}"
  LLAMACPP_PORT="$PORT" uv run python -m harness.cli throughput --model "llamacpp:$STEM" \
    --levels "$level" --server-pid "$SERVER" --json "$@" >"$OUT/level-$slots-$pool-$mode-$level.json" \
    || echo "== $cfg: throughput exited $?"
  grep -h "load_model: initializing\|exceeds the training context\|llama_kv_cache: size" "$log" | sort -u | head -8 \
    || echo "== $cfg: no slot or KV lines in $log"
  if [ "$LONG" -gt 0 ] && [ "$slots" -gt 1 ]; then
    uv run python - "$PORT" "$STEM" "$LONG" <<'PY' || echo "== $cfg: long-context probe failed"
import json, sys, urllib.request
port, stem, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
body = {"model": stem, "max_tokens": 8, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": "ab " * n + "\nReply OK."}]}
req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                             json.dumps(body).encode(), {"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=900) as r:
    got = json.loads(r.read())
print(f"== long-context probe: prompt_tokens {got['usage']['prompt_tokens']} answered "
      f"{got['choices'][0]['message'].get('content', '')[:20]!r}")
PY
  fi
  stop
done
echo "== results in $OUT ($(( $(date +%s) - START ))s)"
