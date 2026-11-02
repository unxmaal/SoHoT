#!/usr/bin/env bash
# Fetch the MiniMax-H3 FL2VA checkpoint for antirez/h3.c.
#
# Only FL2VA is fetched (134.2 GiB of the repo's 464.2 GiB). Ref2VA is optional:
# h3.c probes for Ref2VA/transformer/model.safetensors.index.json and skips the
# whole component when absent, keeping prompt-only FL2VA generation working.
# The repo also ships a flat layout (text_encoder/, transformer/, vae/, ...)
# duplicating the same weights; h3.c wants the task-partitioned form, so the
# flat copy is skipped too.
#
# Resumable: re-running picks up where it left off.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

# The directory the h3 engine reads (engines.h3_model_dir), never a second default. #1450.
DEST="${H3_MODEL_DIR:-$(uv run python -c 'from harness import engines; print(engines.h3_model_dir())')}"
mkdir -p "$DEST"

# ~134 GiB needs headroom; refuse rather than fill the volume.
AVAIL_GB=$(df -Pk "$DEST" | awk 'NR==2 {print int($4 / 1048576)}')
if [ "$AVAIL_GB" -lt 160 ]; then
  echo "FATAL: only ${AVAIL_GB}GB free at $DEST, need ~160GB headroom for 134GiB." >&2
  exit 1
fi
echo "dest  $DEST (${AVAIL_GB}GB free)"

# Publish liveness so h3-weights-status.sh can tell a running download from a
# crashed one without pattern-matching command lines.
LH_LOGS="${LOCALHARNESS_HOME:-$HOME/localharness}/logs"
mkdir -p "$LH_LOGS"
PIDFILE="${H3_DOWNLOAD_PIDFILE:-$LH_LOGS/h3-weights.pid}"
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

# env.sh exported HF_HUB_OFFLINE=1; the fresh interpreter reads it at import (#1457, RULE #813).
HF_HUB_OFFLINE=0 HF_XET_HIGH_PERFORMANCE=1 \
  uv run --no-project --with huggingface_hub python - "$DEST" <<'PY'
import sys, time
from huggingface_hub import snapshot_download

dest = sys.argv[1]
t0 = time.time()
path = snapshot_download(
    repo_id="MiniMaxAI/MiniMax-H3",
    local_dir=dest,
    allow_patterns=["FL2VA/**"],
    max_workers=8,
)
print(f"\ndone in {(time.time()-t0)/60:.1f} min -> {path}")
PY
