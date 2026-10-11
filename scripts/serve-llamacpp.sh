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
source scripts/api-key.sh

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

HOST="${LLAMACPP_HOST:-127.0.0.1}"

# REFUSE TO SERVE A LAN ADDRESS WITHOUT A KEY, and refuse before doing anything
# slow. Binding 0.0.0.0 is a one-word edit and forgetting the key beside it
# leaves a model server answering every host on the subnet. Checked here rather
# than in the caller so it covers every way this script is reached.
case "$HOST" in
  127.0.0.1|localhost|::1) ;;
  *)
    if [ -z "${LLAMACPP_API_KEY_FILE:-}" ]; then
      echo "FATAL: LLAMACPP_HOST is $HOST and LLAMACPP_API_KEY_FILE is unset." >&2
      echo "       A node on a LAN address needs a key of its own; see #684." >&2
      exit 1
    fi ;;
esac

# Loopback and keyless BY DEFAULT, so another machine uses this GPU through the
# gateway on this one, which does hold a key (#482).
#
# A SERVING NODE IS THE EXCEPTION. #684 puts a second node behind the Studio's
# gateway, and that one binds a LAN address and demands a key of its own: there
# is no gateway in front of it on its own machine to do it instead. Set
# LLAMACPP_HOST=0.0.0.0 and LLAMACPP_API_KEY_FILE together. Either alone is a
# mistake, and the open one is the dangerous direction, so the key is checked
# below whenever the host is not loopback.
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
# The key, when there is one. THE SERVER READS THIS FILE ITSELF, so the BOM has
# to be gone from the file rather than from a variable here: pointing
# --api-key-file straight at a key written by PowerShell hands the server three
# bytes of BOM as part of the key. read_api_key normalises it and the cleaned
# copy is what the server is given.
#
# Rewritten on every start, in the run directory under the invoking user's own
# home. The umask is honoured on the Unix half and is advisory on the Windows
# half, where MSYS reports 644 whatever it is asked for; what actually keeps
# the copy private there is the profile directory's own ACL, so do not move
# this to a shared location on the strength of the umask alone.
#
# Not a flag at all when no key file is set: --api-key-file with an empty path
# names nothing and the server refuses to start, which would break the keyless
# default every other machine runs on.
# Expanded below as ${KEY_ARGS[@]+"${KEY_ARGS[@]}"} rather than "${KEY_ARGS[@]}".
# BASH 3.2 TREATS AN EMPTY ARRAY AS UNBOUND under set -u, so the plain spelling
# aborts with "KEY_ARGS[@]: unbound variable" on every machine that sets no key,
# which is most of them. macOS ships 3.2 as /bin/bash, and CTX_ARGS never shows
# this because it always has at least one element. Caught on the macOS runner
# after passing under bash 5 locally.
KEY_ARGS=()
if [ -n "${LLAMACPP_API_KEY_FILE:-}" ]; then
  LH_RUN="${LOCALHARNESS_HOME:-$HOME/localharness}/run"
  mkdir -p "$LH_RUN"
  SERVED_KEY="$LH_RUN/llamacpp-api-key-${LLAMACPP_PORT:-8081}"
  ( umask 077; read_api_key "$LLAMACPP_API_KEY_FILE" > "$SERVED_KEY" ) || exit 1
  KEY_ARGS=(--api-key-file "$SERVED_KEY")
fi

# A dedicated Mac server never sleeps (router-sleep-idle.sh), so no eval case pays a reload (#694).
# --timeout outlasts the slowest load plus the longest reply the knobs allow, so the server never cuts a request first (#694).
exec "$BIN" \
  --jinja \
  --models-dir "$MODELS" \
  --sleep-idle-seconds "${LLAMACPP_SLEEP_IDLE:-$(scripts/router-sleep-idle.sh)}" \
  --timeout "${LLAMACPP_TIMEOUT:-7200}" \
  --models-max "${LLAMACPP_MAX_MODELS:-$(scripts/router-max-models.sh)}" \
  --n-gpu-layers "${LLAMACPP_GPU_LAYERS:-999}" \
  "${CTX_ARGS[@]}" \
  ${KEY_ARGS[@]+"${KEY_ARGS[@]}"} \
  --host "$HOST" \
  --port "${LLAMACPP_PORT:-8081}"
