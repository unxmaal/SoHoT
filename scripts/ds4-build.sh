#!/usr/bin/env bash
# Build antirez/ds4's ds4-server at $DS4_REV under the localharness home. #611.
# Under the home rather than beside the weights, so a models volume swap leaves the build.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/versions.sh

DS4_HOME="${DS4_HOME:-${LOCALHARNESS_HOME:-$HOME/localharness}/ds4}"
CHECKOUT="$DS4_HOME/checkout"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "ds4: this script builds the Metal target; see docs in the ds4 checkout for CUDA" >&2
  exit 3
fi

mkdir -p "$DS4_HOME"
if [ ! -d "$CHECKOUT/.git" ]; then
  echo "ds4: cloning $DS4_REPO_URL into $CHECKOUT" >&2
  git clone --quiet "$DS4_REPO_URL" "$CHECKOUT" >&2
fi
if [ "$(git -C "$CHECKOUT" rev-parse HEAD)" != "$DS4_REV" ]; then
  git -C "$CHECKOUT" fetch --quiet origin >&2
  git -C "$CHECKOUT" checkout --quiet --detach "$DS4_REV" >&2
fi
if [ -n "$(git -C "$CHECKOUT" status --porcelain --untracked-files=no)" ]; then
  echo "FATAL: $CHECKOUT has local edits; the pin would not describe the build" >&2
  exit 1
fi

# Only the server and the CLI; neither needs the network to build. A rebuilt pin relinks.
make -C "$CHECKOUT" -j"$(sysctl -n hw.ncpu)" ds4-server ds4 >&2
echo "$CHECKOUT/ds4-server"
