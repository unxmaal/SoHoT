#!/usr/bin/env bash
# llama.cpp's router: the text lane's engine on a machine with an NVIDIA card.
#
# The counterpart of serve-mlx.sh, and the same shape rather than a different
# one. Both hold the models in ONE process and pick between them by the `model`
# field a request carries, so gateway/config.cuda.yaml names an alias per model
# against a single api_base, exactly as the Mac config does. One port per model
# was the obvious alternative and it is wrong here: a sweep would need every
# candidate resident at once, and 12 GB does not hold two 8B models.
#
# --models-max is 1 rather than the router's default of 4. Four resident models
# is an out-of-memory on a 12 GB card, and harness/memory.py already budgets on
# the assumption that one model is resident and a swap may briefly hold two.
# A machine with 64 GiB or more holds two, so a decide client does not evict a running eval (#644).
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
source scripts/versions.sh

LH_LOGS="${LOCALHARNESS_HOME:-$HOME/localharness}/logs"
mkdir -p "$LH_LOGS"

BIN="${LLAMACPP_BIN:-llama-server}"
if ! command -v "$BIN" >/dev/null 2>&1 && [ ! -x "$BIN" ]; then
  echo "FATAL: $BIN is not on PATH and is not an executable path." >&2
  if [ "${OS:-}" = "Windows_NT" ]; then
    echo "       winget install --id ggml.llamacpp" >&2
  else
    echo "       Build it, or take a release binary:" >&2
    echo "       https://github.com/ggml-org/llama.cpp/releases" >&2
    echo "       An apt llama.cpp, where one exists, is usually built without" >&2
    echo "       CUDA, which leaves the card idle and the lane slow." >&2
  fi
  echo "       Last verified against build $LLAMACPP_BUILD." >&2
  exit 1
fi

# GGUF, not the safetensors the MLX side reads, so it lives beside the rest of
# the cache rather than inside it: huggingface_hub owns $HF_HOME/hub, and a
# directory it does not manage has no business in there.
MODELS="${LLAMACPP_MODELS_DIR:-$HF_HOME/gguf}"
if [ ! -d "$MODELS" ]; then
  echo "FATAL: no model directory at $MODELS" >&2
  echo "       Set LLAMACPP_MODELS_DIR, or fetch one into it:" >&2
  echo "       $BIN -hf Qwen/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M" >&2
  exit 1
fi

# Loopback only: it takes no key, so another machine uses this GPU through the
# gateway on this one, which does (#482). LLAMACPP_HOST overrides.
#
# Port 8081 is mlx_lm.server's, on purpose. Only one of the two runs on any one
# machine, and sharing the port means gateway/config.cuda.yaml differs from the
# Mac config only in which weights it names.
# GIVE THE CARD BACK WHEN IDLE. This machine is a machine with a day job that also
# runs this, and a server left up otherwise holds the model for as long
# as the process lives. Measured on the 4070: a request takes VRAM from
# 2462 to 3296 MiB, and fifteen seconds after the last one it reads 2473
# again. The router reloads on the next request, at the cost of the load
# time and nothing else. Set LLAMACPP_SLEEP_IDLE=-1 to serve full time.
# Context is explicit: unset, a 4B model sized its cache to ~21 GB. #286.
# --jinja: the model's own chat template, which OpenAI tool calls need. #297.
# Per-model context from the store via a preset; a CLI --ctx-size would override it. #498.
PRESET="${LOCALHARNESS_HOME:-$HOME/localharness}/llamacpp-preset-${LLAMACPP_PORT:-8081}.ini"
if uv run python -m harness.context "$PRESET" >/dev/null; then
  CTX_ARGS=(--models-preset "$PRESET")
else
  echo "WARN: no per-model context preset; every model gets ${LLAMACPP_CTX:-16384}" >&2
  CTX_ARGS=(--ctx-size "${LLAMACPP_CTX:-16384}")
fi
exec "$BIN" \
  --jinja \
  --models-dir "$MODELS" \
  --sleep-idle-seconds "${LLAMACPP_SLEEP_IDLE:-300}" \
  --models-max "${LLAMACPP_MAX_MODELS:-$(scripts/router-max-models.sh)}" \
  --n-gpu-layers "${LLAMACPP_GPU_LAYERS:-999}" \
  "${CTX_ARGS[@]}" \
  --host "${LLAMACPP_HOST:-127.0.0.1}" \
  --port "${LLAMACPP_PORT:-8081}"
