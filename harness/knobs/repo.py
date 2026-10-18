"""Knobs of the repo lane (#887)."""
from harness.knobs.base import _k

KNOBS = [
    _k("repo_env_timeout", ["evals/repo.py:ENV_TIMEOUT_S"], [600.0, 1800.0, 3600.0],
       note="seconds `uv sync --frozen` may take to build a base commit's environment; a miss is environment_error (#887)"),
    _k("repo_git_timeout", ["evals/repo.py:GIT_TIMEOUT_S"], [120.0, 600.0, 1800.0],
       note="seconds one git clone, fetch or worktree step may take; a miss is environment_error (#887)"),
    _k("repo_test_timeout", ["evals/repo.py:TEST_TIMEOUT_S"], [120.0, 300.0, 600.0, 1200.0],
       lanes=("repo",), limit="repo_test_timeout_s", receipt="knobs",
       note="seconds the sandboxed pytest run of a repo case may take before it is killed (#887)"),
]

NOT_GATING = {
    "harness/completion.py:LADDER[repo]": "rungs only a --budget-ladder run climbs, recorded as Receipt.budget_ladder; "
    "a plain run asks the one reply_budget (#887)",
    "evals/repo.py:Grade.test_s": "how long the graded tests took, as reported (#887)",
    "evals/importers/history.py:HOLDOUT_FRACTION": "share of history tasks frozen into the held-out split by "
    "SPLIT_SEED and pinned in history.json; moving it reshuffles which tasks are quoted, so it is never swept (#995)",
}
