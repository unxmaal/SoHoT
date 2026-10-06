#!/usr/bin/env bash
# LiteLLM gateway. The only address text clients ever learn.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
source scripts/versions.sh
LH_LOGS="${LOCALHARNESS_HOME:-$HOME/localharness}/logs"
mkdir -p "$LH_LOGS"

# Which config, so one launcher serves both machines: the Mac names
# mlx-community weights, gateway/config.cuda.yaml names GGUF ones.
#
#   GATEWAY_CONFIG=gateway/config.cuda.yaml ./scripts/serve-gateway.sh
#
# Opt out of LiteLLM's Responses API adapter. Without it, POST /v1/messages is
# routed to POST /v1/responses upstream, which mlx_lm.server does not implement,
# and every Anthropic-shaped request 404s.
#
# Also set as a litellm_settings: key in gateway/config.yaml. Both work
# independently (controlled A/B, docs/validation-log.md). Belt and braces,
# because the failure mode is a confusing 404 rather than a clear error.
export LITELLM_USE_CHAT_COMPLETIONS_URL_FOR_ANTHROPIC_MESSAGES=1

# The cloud-opus alias's key, from the login Keychain so it is never in a file:
#   security add-generic-password -a "$USER" -s localharness-anthropic -w
if [ -z "${ANTHROPIC_API_KEY:-}" ] && command -v security >/dev/null 2>&1; then
  ANTHROPIC_API_KEY="$(security find-generic-password -s localharness-anthropic -w 2>/dev/null || true)"
  export ANTHROPIC_API_KEY
fi

# The master key (#482): created on first start, from the Keychain on the Mac
# and a 0600 file elsewhere. Without one LiteLLM serves everyone, so refuse.
LITELLM_MASTER_KEY="$(uv run python -m harness.gateway_key ensure)" || LITELLM_MASTER_KEY=""
if [ -z "$LITELLM_MASTER_KEY" ]; then
  echo "FATAL: no gateway key, and the gateway will not listen without one." >&2
  echo "       Create it with: soh gateway key" >&2
  exit 1
fi
export LITELLM_MASTER_KEY

# Binds every interface by default. Deliberate: the point of the machine is that
# other machines on the LAN can use the GPU, with the Studio serving and the
# Apple Silicon machine as a client. Every request needs the key above; the
# engines behind it listen on loopback only. GATEWAY_HOST=127.0.0.1 keeps it local.
#
# --host is passed explicitly regardless. LiteLLM's own default is 0.0.0.0, so
# omitting the flag would make the binding invisible: every doc in this repo
# once said "127.0.0.1:4000" while lsof said "*:4000". State it, whichever it is.
# UTF-8 REGARDLESS OF THE MACHINE'S CODEPAGE. Python picks its stdio encoding
# from the locale, which is cp1252 on a stock Windows install, and anything
# printing a character outside it dies. LiteLLM's startup banner does exactly
# that, so the gateway exited during startup with a UnicodeEncodeError while
# every one of its own settings was correct. Only visible when output is
# redirected to a file, which is how a service runs.
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# The base config plus sohot-<lane> aliases for what each text lane has adopted. #297.
CONFIG="${GATEWAY_CONFIG:-gateway/config.yaml}"
SERVED="$(uv run python -m harness.gateway "$CONFIG")" || SERVED="$CONFIG"

exec uv run --python 3.12 --with "$LITELLM_PIN" \
  litellm --config "$SERVED" \
  --host "${GATEWAY_HOST:-0.0.0.0}" --port "${GATEWAY_PORT:-4000}"
