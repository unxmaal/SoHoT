# shellcheck shell=bash
# The nimble engine's environment (#423). Sourced by nimble-score.sh; never run
# directly. Clones bespokelabsai/nimble at $NIMBLE_REV and builds a Python 3.12
# venv holding its MLX scorer plus torch and peft for the one-time adapter merge.
# Sets $PY and $NIMBLE_ROOT.

NIMBLE_HOME="${NIMBLE_HOME:-${LOCALHARNESS_HOME:-$HOME/localharness}/nimble}"
NIMBLE_ROOT="${NIMBLE_ROOT:-$NIMBLE_HOME/checkout}"
NIMBLE_VENV="${NIMBLE_VENV:-$NIMBLE_HOME/venv}"
export NIMBLE_MODELS="${NIMBLE_MODELS:-$NIMBLE_HOME/models}"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "nimble: the MLX scorer needs Apple Silicon; this is $(uname -s) $(uname -m)" >&2
  exit 3
fi

if [ ! -d "$NIMBLE_ROOT/.git" ]; then
  echo "nimble: cloning $NIMBLE_REPO_URL into $NIMBLE_ROOT" >&2
  git clone --quiet "$NIMBLE_REPO_URL" "$NIMBLE_ROOT" >&2
fi
if [ "$(git -C "$NIMBLE_ROOT" rev-parse HEAD)" != "$NIMBLE_REV" ]; then
  git -C "$NIMBLE_ROOT" fetch --quiet origin >&2
  git -C "$NIMBLE_ROOT" checkout --quiet "$NIMBLE_REV" >&2
fi

NIMBLE_VENV_PINS=("$NIMBLE_MLX_PIN" "$NIMBLE_MLX_LM_PIN" "$TRANSFORMERS_PIN" "$NIMBLE_TORCH_PIN" "$PEFT_PIN"
                  "$ACCELERATE_PIN" "$SAFETENSORS_PIN" "$HUGGINGFACE_HUB_PIN")

# The stamp carries the pins and every installed dist, so a moved pin or a hand install rebuilds it. #1037.
_nimble_dists() {
  local d
  for d in "$NIMBLE_VENV"/lib/python*/site-packages/*.dist-info; do
    if [ -d "$d" ]; then printf '%s\n' "${d##*/}"; fi
  done | LC_ALL=C sort
}

PY="$NIMBLE_VENV/bin/python"
if [ ! -x "$PY" ] || [ "$(cat "$NIMBLE_VENV/.pins" 2>/dev/null)" != "$(printf '%s\n' "${NIMBLE_VENV_PINS[*]}"; _nimble_dists)" ]; then
  echo "nimble: building its environment in $NIMBLE_VENV" >&2
  # From empty: uv pip install never removes what an older pin or a hand install left. #1037.
  uv venv --clear --python 3.12 "$NIMBLE_VENV" >&2
  VIRTUAL_ENV="$NIMBLE_VENV" uv pip install "${NIMBLE_VENV_PINS[@]}" >&2
  [ ! -x "$PY" ] || { printf '%s\n' "${NIMBLE_VENV_PINS[*]}"; _nimble_dists; } > "$NIMBLE_VENV/.pins"
fi
if [ ! -x "$PY" ]; then
  echo "FATAL: no interpreter in $NIMBLE_VENV after building it" >&2
  exit 1
fi

# nimble is imported from its checkout; harness/nimble_score.py from this one.
export PYTHONPATH="$NIMBLE_ROOT:$PWD${PYTHONPATH:+:$PYTHONPATH}"
