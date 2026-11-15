#!/usr/bin/env bash
# Compile scripts/locks/NAME.txt from versions.sh pins, so each `uv run --with` resolves to one cached environment. #2049
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/versions.sh

lock() {
  local name="$1" platform="$2"; shift 2
  local spec in
  in="$(mktemp)"
  for spec in "$@"; do printf '%s\n' "$spec" >> "$in"; done
  uv pip compile --quiet --python 3.12 "$platform" --no-header --no-annotate "$in" -o "scripts/locks/$name.txt"
  rm -f "$in"
}

mkdir -p scripts/locks
lock litellm --universal "$LITELLM_PIN"
MACOSX_DEPLOYMENT_TARGET=14.0 lock tts --python-platform=aarch64-apple-darwin "$MLX_AUDIO_PIN" "$UVICORN_PIN" "$WEBRTCVAD_PIN" "$FASTAPI_PIN" \
  "$MULTIPART_PIN" "$SETUPTOOLS_PIN" "$MISAKI_PIN" "$SOUNDFILE_PIN" "$SPACY_PIN" "$PRESHED_PIN" "$EN_CORE_WEB_SM_PIN"
lock hub --universal "$HUGGINGFACE_HUB_PIN"
