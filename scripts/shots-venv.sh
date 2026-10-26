# shellcheck shell=bash
# The shots lane's environment (#1208). Sourced by shots.sh; never run directly.
# CPU torch, TransNetV2 and PySceneDetect in a venv of their own. Rebuilt when a pin moves.
# Sets $PY.

SHOTS_VENV="${SHOTS_VENV:-${LOCALHARNESS_HOME:-$HOME/localharness}/venvs/shots}"

_shots_python() {
  if [ -x "$SHOTS_VENV/Scripts/python.exe" ]; then
    printf '%s\n' "$SHOTS_VENV/Scripts/python.exe"
  elif [ -x "$SHOTS_VENV/bin/python" ]; then
    printf '%s\n' "$SHOTS_VENV/bin/python"
  fi
}

if [ "$(uname -s)" = "Darwin" ]; then
  SHOTS_TORCH=("$TORCH_MPS_PIN")
else
  SHOTS_TORCH=(--index-url "$TORCH_CPU_INDEX" "$TORCH_CPU_PIN")
fi
SHOTS_PINS=("$TRANSNETV2_PIN" "$SCENEDETECT_PIN" "$OPENCV_PIN" "$NUMPY_PIN")
SHOTS_STAMP="${SHOTS_TORCH[*]} ${SHOTS_PINS[*]}"

_shots_dists() {
  local d
  for d in "$SHOTS_VENV"/lib/python*/site-packages/*.dist-info "$SHOTS_VENV"/Lib/site-packages/*.dist-info; do
    if [ -d "$d" ]; then printf '%s\n' "${d##*/}"; fi
  done | LC_ALL=C sort
}

PY="$(_shots_python)"
if [ -z "$PY" ] || [ "$(cat "$SHOTS_VENV/.pins" 2>/dev/null)" != "$(printf '%s\n' "$SHOTS_STAMP"; _shots_dists)" ]; then
  echo "shots: building its environment in $SHOTS_VENV" >&2
  uv venv --clear --python 3.12 "$SHOTS_VENV" >&2
  VIRTUAL_ENV="$SHOTS_VENV" uv pip install "${SHOTS_TORCH[@]}" >&2
  VIRTUAL_ENV="$SHOTS_VENV" uv pip install "${SHOTS_PINS[@]}" >&2
  PY="$(_shots_python)"
  [ -z "$PY" ] || { printf '%s\n' "$SHOTS_STAMP"; _shots_dists; } > "$SHOTS_VENV/.pins"
fi
if [ -z "$PY" ]; then
  echo "FATAL: no interpreter in $SHOTS_VENV after building it" >&2
  exit 1
fi

# harness/shot_detect.py is imported from this checkout; torch and the detectors from the venv.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
