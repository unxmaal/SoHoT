#!/usr/bin/env bash
# The live store's audit: run nightly by launchd, and by `launchd.sh install` after a deploy. #492.
# Not a server: it reads the store read-only, prints each check, and exits non-zero on a failure.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== audit $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
# After the header, so a refusal is logged under it. #1481.
source scripts/env.sh
exec uv run soh audit
