"""Knobs of the repo lane (#887)."""
from harness.knobs.base import _k

KNOBS = [
    _k("history_max_lines", ["evals/importers/history.py:MAX_LINES"], [150, 400],
       note="changed source lines a fix may have and still be surveyed; 150 was the #888 pilot cap, which "
            "stays the small stratum (history.SMALL) the local pilot runs (#997)"),
    _k("history_max_source_files", ["evals/importers/history.py:MAX_SOURCE_FILES"], [3, 8],
       note="source files a fix may change and still be surveyed as a history task; 3 was the #888 pilot's "
            "local-model cap, 8 takes the bigger fixes Claude Code arms can do (#997)"),
    _k("repo_env_timeout", ["evals/repo.py:ENV_TIMEOUT_S"], [600.0, 1800.0, 3600.0],
       note="seconds `uv sync --frozen` may take to build a base commit's environment; a miss is environment_error (#887)"),
    _k("repo_gate_min_tasks", ["harness/repo_gate.py:MIN_TASKS"], [20, 30, 50],
       note="repo tasks valid on this machine before a code adoption must first win the repo lane (#889)"),
    _k("repo_git_timeout", ["evals/repo.py:GIT_TIMEOUT_S"], [120.0, 600.0, 1800.0],
       note="seconds one git clone, fetch or worktree step may take; a miss is environment_error (#887)"),
    _k("repo_test_timeout", ["evals/repo.py:TEST_TIMEOUT_S"], [120.0, 300.0, 600.0, 1200.0],
       lanes=("repo",), limit="repo_test_timeout_s", receipt="knobs",
       note="seconds the sandboxed pytest run of a repo case may take before it is killed (#887)"),
]

NOT_GATING = {
    "evals/importers/history.py:SMALL[files]": "labels a surveyed task small or large; it admits or drops nothing, "
    "MAX_SOURCE_FILES does (#997)",
    "evals/importers/history.py:SMALL[lines]": "labels a surveyed task small or large; it admits or drops nothing, "
    "MAX_LINES does (#997)",
    "harness/completion.py:LADDER[repo]": "rungs only a --budget-ladder run climbs, recorded as Receipt.budget_ladder; "
    "a plain run asks the one reply_budget (#887)",
    "evals/repo.py:Grade.test_s": "how long the graded tests took, as reported (#887)",
    "evals/importers/history.py:HOLDOUT_FRACTION": "share of history tasks frozen into the held-out split by "
    "SPLIT_SEED and pinned in history.json; moving it reshuffles which tasks are quoted, so it is never swept (#995)",
}
