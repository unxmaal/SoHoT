#!/usr/bin/env bash
# Claude Code statusLine: prints a short line and logs the plan's rate-limit readings for `soh ledger`. #826.
exec uv run --no-project --quiet --python 3.12 python -I "$(dirname "$0")/../harness/statusline.py"
