"""Knobs of fix (#2035)."""
from harness.knobs.base import _k

KNOBS = [
    _k("fix_attempts", ["harness/fix.py:ATTEMPTS"], [1, 2, 3],
       note="local attempts per issue before it escalates; the second is told why the gate refused (#2035)"),
    _k("fix_exec_max_turns", ["harness/fix.py:EXEC_MAX_TURNS"], [15, 30, 50], unit="turns",
       note="agent turns of one local step before Claude Code stops it (#2035)"),
    _k("fix_exec_timeout_s", ["harness/fix.py:EXEC_TIMEOUT_S"], [300, 600, 1200], unit="s",
       note="wall seconds of one local step (#2035)"),
    _k("fix_gate_timeout_s", ["harness/fix.py:GATE_TIMEOUT_S"], [120, 240, 480], unit="s",
       note="wall seconds of one gate command; past it the gate refuses (#2035)"),
    _k("fix_max_files", ["harness/fix.py:MAX_FILES"], [1, 3, 5], unit="files",
       note="source files one plan may change; more is out of class (#2035)"),
    _k("fix_plan_max_turns", ["harness/fix.py:PLAN_MAX_TURNS"], [6, 12, 20], unit="turns",
       note="agent turns of the cloud plan call (#2035)"),
    _k("fix_plan_timeout_s", ["harness/fix.py:PLAN_TIMEOUT_S"], [300, 600, 1200], unit="s",
       note="wall seconds of the cloud plan call (#2035)"),
    _k("fix_plan_token_cap", ["harness/fix.py:PLAN_TOKEN_CAP"], [10000, 20000, 30000], unit="tokens",
       note="counted cloud tokens one plan may spend before the issue escalates (#2035)"),
]

NOT_GATING = {
    "harness/fix.py:Record.seconds": "the record's measured wall time, written after the outcome is decided (#2035)",
    "harness/commands/fix.py:_gh->fix.run_cmd(timeout)": "how long a gh read may take; a failure stops the command with the error, never scores an issue (#2035)",
}
