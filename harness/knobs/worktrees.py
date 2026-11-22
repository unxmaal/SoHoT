"""Knobs of worktrees (#2114)."""

KNOBS = []

NOT_GATING = {
    "harness/worktrees.py:STEP_TIMEOUT_S": "a git or gh step that misses it keeps the worktree; no verdict reads it (#2114)",
}
