"""Knobs of the deploy guard in scripts/launchd.sh (#870)."""
M = "harness/deploy_guard.py"

KNOBS = []

NOT_GATING = {
    f"{M}:GH_TIMEOUT_S": "how long gh may take to say whether check-macos passed; a timeout refuses the deploy (#870)",
}
