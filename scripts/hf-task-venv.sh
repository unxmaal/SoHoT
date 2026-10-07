# shellcheck shell=bash
# The hf-task engines' environment (#562). Sourced by hf-task.sh; never run
# directly. torch from the machine's own index, transformers from PyPI, in a
# venv of its own so `uv sync` never pulls a torch. Rebuilt when a pin moves.
# Sets $PY.

HF_TASK_VENV="${HF_TASK_VENV:-${LOCALHARNESS_HOME:-$HOME/localharness}/venvs/hf-task}"

_hf_task_python() {
  if [ -x "$HF_TASK_VENV/Scripts/python.exe" ]; then
    printf '%s\n' "$HF_TASK_VENV/Scripts/python.exe"
  elif [ -x "$HF_TASK_VENV/bin/python" ]; then
    printf '%s\n' "$HF_TASK_VENV/bin/python"
  fi
}

if [ "$(uname -s)" = "Darwin" ]; then
  HF_TASK_TORCH=("$TORCH_MPS_PIN" "$TORCHVISION_MPS_PIN")
else
  HF_TASK_TORCH=(--index-url "$TORCH_CUDA_INDEX" "$TORCH_CUDA_PIN" "$TORCHVISION_CUDA_PIN")
fi
HF_TASK_PINS=("$TRANSFORMERS_PIN" "$ACCELERATE_PIN" "$SAFETENSORS_PIN" "$PILLOW_PIN"
              "$SENTENCEPIECE_PIN" "$SENTENCE_TRANSFORMERS_PIN")
HF_TASK_STAMP="${HF_TASK_TORCH[*]} ${HF_TASK_PINS[*]}"

PY="$(_hf_task_python)"
if [ -z "$PY" ] || [ "$(cat "$HF_TASK_VENV/.pins" 2>/dev/null)" != "$HF_TASK_STAMP" ]; then
  echo "hf-task: building its environment in $HF_TASK_VENV" >&2
  [ -n "$PY" ] || uv venv --python 3.12 "$HF_TASK_VENV" >&2
  VIRTUAL_ENV="$HF_TASK_VENV" uv pip install "${HF_TASK_TORCH[@]}" >&2
  VIRTUAL_ENV="$HF_TASK_VENV" uv pip install "${HF_TASK_PINS[@]}" >&2
  PY="$(_hf_task_python)"
  [ -z "$PY" ] || printf '%s' "$HF_TASK_STAMP" > "$HF_TASK_VENV/.pins"
fi
if [ -z "$PY" ]; then
  echo "FATAL: no interpreter in $HF_TASK_VENV after building it" >&2
  exit 1
fi

# harness/hf_task.py is imported from this checkout; torch and transformers from the venv.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
