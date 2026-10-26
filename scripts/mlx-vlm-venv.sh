# shellcheck shell=bash
# The vision lane's mlx-vlm labeller environment (#1282). Sourced by mlx-vlm.sh;
# never run directly. Apple Silicon only. Rebuilt when a pin moves. Sets $PY.

MLX_VLM_VENV="${MLX_VLM_VENV:-${LOCALHARNESS_HOME:-$HOME/localharness}/venvs/mlx-vlm}"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "FATAL: mlx-vlm runs on Apple Silicon only; use hf-vlm: or llamacpp-vlm: here" >&2
  exit 1
fi
# transformers 5 resolves Idefics3 and Qwen-VL image processors only with torch and torchvision present. #1282.
MLX_VLM_PINS=("$MLX_VLM_PIN" "$MLX_VLM_MLX_PIN" "$TRANSFORMERS_PIN" "$PILLOW_PIN" "$HUGGINGFACE_HUB_PIN"
              "$TORCH_MPS_PIN" "$TORCHVISION_MPS_PIN")
MLX_VLM_STAMP="${MLX_VLM_PINS[*]}"

# The stamp carries every installed dist, so a hand install after the build rebuilds it too. #1032.
_mlx_vlm_dists() {
  local d
  for d in "$MLX_VLM_VENV"/lib/python*/site-packages/*.dist-info; do
    if [ -d "$d" ]; then printf '%s\n' "${d##*/}"; fi
  done | LC_ALL=C sort
}

PY="$MLX_VLM_VENV/bin/python"
if [ ! -x "$PY" ] || [ "$(cat "$MLX_VLM_VENV/.pins" 2>/dev/null)" != "$(printf '%s\n' "$MLX_VLM_STAMP"; _mlx_vlm_dists)" ]; then
  echo "mlx-vlm: building its environment in $MLX_VLM_VENV" >&2
  # From empty: uv pip install never removes what an older pin or a hand install left. #1032.
  uv venv --clear --python 3.12 "$MLX_VLM_VENV" >&2
  VIRTUAL_ENV="$MLX_VLM_VENV" uv pip install "${MLX_VLM_PINS[@]}" >&2
  [ ! -x "$PY" ] || { printf '%s\n' "$MLX_VLM_STAMP"; _mlx_vlm_dists; } > "$MLX_VLM_VENV/.pins"
fi
if [ ! -x "$PY" ]; then
  echo "FATAL: no interpreter in $MLX_VLM_VENV after building it" >&2
  exit 1
fi

# harness/mlx_vlm_label.py is imported from this checkout; mlx_vlm from the venv.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
