"""Knobs of the repo lane (#887)."""
from harness.knobs.base import _k

KNOBS = [
    _k("history_max_lines", ["evals/importers/history.py:MAX_LINES"], [150, 400],
       note="changed source lines a fix may have and still be surveyed; 150 was the #888 pilot cap, which "
            "stays the small stratum (history.SMALL) the local pilot runs (#997)"),
    _k("history_max_source_files", ["evals/importers/history.py:MAX_SOURCE_FILES"], [3, 8],
       note="source files a fix may change and still be surveyed as a history task; 3 was the #888 pilot's "
            "local-model cap, 8 takes the bigger fixes Claude Code arms can do (#997)"),
    _k("repair_case_timeout", ["evals/runners/repo_repair.py:CASE_TIMEOUT_S"], [600.0, 1200.0, 1800.0, 3600.0],
       lanes=("repo",), limit="repair_case_timeout_s", unit="s", receipt="knobs", unrecorded=1800.0,
       note="seconds of a repair-harness case's turns and test runs, checkout and env build excluded; Ornith's "
            "single-shot median is 142 s (run 1150), so 1800 s is ~12 single-shot cases' worth (#890)"),
    _k("repair_max_steps", ["evals/runners/repo_repair.py:MAX_STEPS"], [10, 20, 30, 50],
       lanes=("repo",), limit="repair_max_steps", unit="turns", receipt="knobs", unrecorded=30,
       note="model turns a repair-harness case may take; a <=20-line fix needs ~3-5 reads, 1-3 patches, 1-3 test "
            "runs and finish, so 30 is about twice that; unmeasured until the first repair run (#890)"),
    _k("repair_max_tokens", ["evals/runners/repo_repair.py:MAX_TOKENS"], [20000, 40000, 60000, 120000],
       lanes=("repo",), limit="repair_max_tokens", unit="tokens", receipt="knobs", unrecorded=60000,
       note="tokens a repair-harness case may generate over all its turns; Ornith's single-shot rows stop at "
            "the 18160-token yield point (FINDING #709), so 60000 is ~3 single-shot attempts (#890)"),
    _k("repair_output_cap", ["evals/repo_tools.py:OUTPUT_CAP"], [4000, 8000, 16000],
       lanes=("repo",), limit="repair_output_cap", unit="bytes", receipt="knobs", unrecorded=8000,
       note="bytes of one repair-harness tool result the model is sent, the rest cut with a note; 8000 is ~2k "
            "tokens, so 30 turns of full results stay inside a 64k context (#890)"),
    _k("repo_doc_patterns", ["evals/repo.py:DOC_PATTERNS"], [(), ("*.md", "*.rst", "docs/**", "CHANGELOG*")],
       note="files whose hunks may fail to apply and be left out, the rest graded, when no test names them; "
            "() grades every failed hunk invalid_patch as before #1107"),
    _k("repo_env_timeout", ["evals/repo.py:ENV_TIMEOUT_S"], [600.0, 1800.0, 3600.0],
       note="seconds `uv sync --frozen` may take to build a base commit's environment; a miss is environment_error (#887)"),
    _k("repo_gate_min_tasks", ["harness/repo_gate.py:MIN_TASKS"], [20, 30, 50],
       note="repo tasks valid on this machine before a code adoption must first win the repo lane (#889)"),
    _k("repo_git_timeout", ["evals/repo.py:GIT_TIMEOUT_S"], [120.0, 600.0, 1800.0],
       note="seconds one git clone, fetch or worktree step may take; a miss is environment_error (#887)"),
    _k("repo_max_fix_lines", ["evals/repo_size.py:MAX_FIX_LINES"], [0, 20, 56, 115],
       note="largest reference fix (non-test lines base..fix) --max-fix-lines keeps, 0 all; 20/56/115 are the "
            "upper quartile edges of the 108-case exam, where Ornith passes 11/27, 1/27, 0/27 (FINDING #709, #890)"),
    _k("repo_test_timeout", ["evals/repo.py:TEST_TIMEOUT_S"], [120.0, 300.0, 600.0, 1200.0],
       lanes=("repo",), limit="repo_test_timeout_s", unit="s", receipt="knobs",
       note="seconds the sandboxed pytest run of a repo case may take before it is killed (#887)"),
    _k("transcripts_commit_after", ["evals/importers/transcripts.py:COMMIT_AFTER_S"], [30, 120, 600],
       note="seconds a printed commit's committer date may follow the tool output and still be its evidence (#1095)"),
    _k("transcripts_commit_before", ["evals/importers/transcripts.py:COMMIT_BEFORE_S"], [600, 1800, 3600],
       note="seconds a printed commit's committer date may precede the tool output (hooks, a push after it) (#1095)"),
    _k("transcripts_cut_budget", ["evals/session_cut.py:BUDGET_BYTES"], [12000, 24000, 48000],
       note="bytes of the session a transcript case's prompt keeps before the first edit (#1095)"),
    _k("transcripts_cut_command_cap", ["evals/session_cut.py:COMMAND_CAP_BYTES"], [0, 400, 1500],
       note="bytes of a non-read command's output a cut keeps; past it the body goes, as it may quote other people (#1095)"),
    _k("transcripts_cut_output_cap", ["evals/session_cut.py:OUTPUT_CAP_BYTES"], [500, 1500, 4000],
       note="bytes of one tool output a cut keeps; a larger non-read output loses its body (#1095)"),
    _k("transcripts_leak_min_chars", ["evals/session_cut.py:LEAK_MIN_CHARS"], [8, 16, 32],
       note="characters an added fix line needs before its presence in a cut counts as a leak (#1095)"),
    _k("transcripts_min_cut_bytes", ["evals/importers/transcripts.py:MIN_CUT_BYTES"], [500, 1000, 2000],
       note="bytes a cut needs beyond its header; a smaller one is the request alone and drops as cut_too_short (#1095)"),
]

#: Knobs only the repair harness reads; a patch-harness identity leaves them out so its stored draws stay reusable.
REPAIR = ("repair_case_timeout", "repair_max_steps", "repair_max_tokens", "repair_output_cap")

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
