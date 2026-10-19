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
fi

if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  EXTRA="[mlx]"
  DECIDER_MLX=("$NIMBLE_MLX_PIN" "$DECIDER_MLX_LM_PIN")
else
  EXTRA=""
  DECIDER_MLX=()
fi
# The checkout is the first word; venv_drift starts its closure from the dist that install leaves. #1037.
DECIDER_VENV_PINS=("${DECIDER_ROOT}${EXTRA}" "$NIMBLE_TORCH_PIN" "$TRANSFORMERS_PIN" "$PEFT_PIN" "$ACCELERATE_PIN"
                   "$SAFETENSORS_PIN")
DECIDER_STAMP="$DECIDER_REV ${DECIDER_MLX[*]+${DECIDER_MLX[*]}} ${DECIDER_VENV_PINS[*]}"

# The stamp carries the revision, the pins and every installed dist, so any of them moving rebuilds it. #1037.
_decider_dists() {
  local d
  for d in "$DECIDER_VENV"/lib/python*/site-packages/*.dist-info; do
    if [ -d "$d" ]; then printf '%s\n' "${d##*/}"; fi
  done | LC_ALL=C sort
}

PY="$DECIDER_VENV/bin/python"
if [ ! -x "$PY" ] || [ "$(cat "$DECIDER_VENV/.pins" 2>/dev/null)" != "$(printf '%s\n' "$DECIDER_STAMP"; _decider_dists)" ]; then
  echo "decider: building its environment in $DECIDER_VENV" >&2
  # From empty: uv pip install never removes what an older revision, pin or hand install left. #1032, #1037.
  uv venv --clear --python 3.12 "$DECIDER_VENV" >&2
  # SETUPTOOLS_SCM_PRETEND_VERSION: the clone has no release tag to version from.
  SETUPTOOLS_SCM_PRETEND_VERSION="0.1.0+g${DECIDER_REV:0:7}" VIRTUAL_ENV="$DECIDER_VENV" \
    uv pip install "${DECIDER_VENV_PINS[@]}" ${DECIDER_MLX[@]+"${DECIDER_MLX[@]}"} >&2
  [ ! -x "$PY" ] || { printf '%s\n' "$DECIDER_STAMP"; _decider_dists; } > "$DECIDER_VENV/.pins"
fi
if [ ! -x "$PY" ]; then
  echo "FATAL: no interpreter in $DECIDER_VENV after building it" >&2
  exit 1
fi

# harness/decider_score.py is imported from this checkout; strands_decider from the venv.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
