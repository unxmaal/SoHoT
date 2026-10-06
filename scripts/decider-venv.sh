# shellcheck shell=bash
# The decider engine's environment (#467). Sourced by decider-score.sh; never run
# directly. Clones strands-labs/strands-decider at $DECIDER_REV and installs it,
# with the mlx extra on Apple Silicon, into a Python 3.12 venv. Sets $PY.

DECIDER_HOME="${DECIDER_HOME:-${LOCALHARNESS_HOME:-$HOME/localharness}/decider}"
DECIDER_ROOT="${DECIDER_ROOT:-$DECIDER_HOME/checkout}"
DECIDER_VENV="${DECIDER_VENV:-$DECIDER_HOME/venv}"

if [ ! -d "$DECIDER_ROOT/.git" ]; then
  echo "decider: cloning $DECIDER_REPO_URL into $DECIDER_ROOT" >&2
  git clone --quiet "$DECIDER_REPO_URL" "$DECIDER_ROOT" >&2
fi
if [ "$(git -C "$DECIDER_ROOT" rev-parse HEAD)" != "$DECIDER_REV" ]; then
  git -C "$DECIDER_ROOT" fetch --quiet origin >&2
  git -C "$DECIDER_ROOT" checkout --quiet "$DECIDER_REV" >&2
  rm -f "$DECIDER_VENV/.rev"
fi

EXTRA=""
MLX_PINS=()
if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  EXTRA="[mlx]"
  MLX_PINS=("$NIMBLE_MLX_PIN" "$DECIDER_MLX_LM_PIN")
fi

PY="$DECIDER_VENV/bin/python"
if [ ! -x "$PY" ] || [ "$(cat "$DECIDER_VENV/.rev" 2>/dev/null)" != "$DECIDER_REV" ]; then
  echo "decider: building its environment in $DECIDER_VENV" >&2
  [ -x "$PY" ] || uv venv --python 3.12 "$DECIDER_VENV" >&2
  # SETUPTOOLS_SCM_PRETEND_VERSION: the clone has no release tag to version from.
  SETUPTOOLS_SCM_PRETEND_VERSION="0.1.0+g${DECIDER_REV:0:7}" VIRTUAL_ENV="$DECIDER_VENV" \
    uv pip install "${DECIDER_ROOT}${EXTRA}" ${MLX_PINS[@]+"${MLX_PINS[@]}"} "$NIMBLE_TORCH_PIN" \
    "$TRANSFORMERS_PIN" "$PEFT_PIN" "$ACCELERATE_PIN" "$SAFETENSORS_PIN" >&2
  echo "$DECIDER_REV" > "$DECIDER_VENV/.rev"
fi
if [ ! -x "$PY" ]; then
  echo "FATAL: no interpreter in $DECIDER_VENV after building it" >&2
  exit 1
fi

# harness/decider_score.py is imported from this checkout; strands_decider from the venv.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
