"""Knobs of the check-macos CI job: its timeout, budget warning, one rerun, and what a slow run names (#1146, #1520)."""
from harness.knobs.base import _k

B = "harness/ci_budget.py"
T = "harness/suite_time.py"
R = "harness/ci_rerun.py"

KNOBS = [
    _k("ci_budget_warn", [f"{B}:WARN_SHARE"], [0.7, 0.8, 0.9],
       note="share of its timeout a CI job may use before ci_budget prints a GitHub warning (#1146)"),
    _k("ci_hang_s", [f"{T}:HANG_S"], [120.0, 180.0, 300.0],
       note="seconds a test in flight, or a suite with nothing starting or ending, makes a cancelled run a hang "
            "rather than a slow suite; equal to tests/conftest HANG_DUMP_S (#1520)"),
    _k("ci_macos_reruns", [f"{R}:RERUNS"], [0, 1, 2],
       note="automatic reruns of a push-to-main check run whose check-macos hit its timeout on main's tip; one, "
            "so runner variance cannot block a deploy and a suite that is simply too slow still fails (#1520)"),
    _k("ci_macos_timeout", [f"{B}:MACOS_TIMEOUT_MIN"], [35, 45, 56, 70],
       note="check-macos timeout-minutes: ci_budget.HOST_FACTOR 1.4x the push job p95 on the 3-vCPU M1 class with "
            "timeouts projected (39.1 min over 54 runs to 2026-11-13, 15 of them cut at 35; python -m harness.ci_history); "
            "a slow M1 host ran 1.4x the run before it (41692522061 vs 41687128099) and 2.0x in #1146 (#1520, #1590)"),
    _k("ci_slower_added", [f"{T}:SLOWER_ADDED_S"], [10.0, 30.0, 60.0],
       note="seconds more than on the last main run a test must take to be named slower; with ci_slower_ratio, "
            "42 ordered pairs of 7 runs named only the two tests #1181 made wait 120 s (#1146)"),
    _k("ci_slower_ratio", [f"{T}:SLOWER_RATIO"], [3.0, 5.0, 8.0],
       note="times its last main run a test must take to be named slower; 3x with 20 s also named two tests "
            "that vary by runner (#1146)"),
]

_RULE = "what timeout a job's measured p95 asks for, which ci_history reports and a test holds ci.yml to; it gates no run (#1590)"

NOT_GATING = {
    **{f"{B}:HOST_FACTOR[{j}]": _RULE for j in ("check-linux", "check-macos", "check-postgres", "check-windows")},
    "harness/ci_history.py:_gh->subprocess.run(timeout)": "how long one gh call of a CI history read may take; it "
                                                          "measures past runs and gates nothing (#1520)",
    "harness/ci_rerun.py:_gh->subprocess.run(timeout)": "how long one gh call deciding a rerun may take; a stuck "
                                                        "call fails the rerun job, never a check (#1520)",
    "scripts/ci-retry.sh:CI_RETRY_ATTEMPTS": "how many times CI runs `uv sync` before the job fails; a network "
                                             "blip retried is the same install, and a persistent failure still fails (#1440)",
    "scripts/ci-retry.sh:CI_RETRY_DELAY": "seconds before CI's first `uv sync` retry, doubling after; it only "
                                          "spaces attempts at the same install (#1440)",
}

NEVER_CUTS = {
    f"{R}:RERUNS": "whether a timed-out main run is retried; the check still reports what it found (#1520)",
    f"{T}:HANG_S": "which words a cancelled run's report uses, slow suite or hang; every test still runs (#1520)",
    "harness/ci_budget.py:MACOS_TIMEOUT_MIN": "a copy of check-macos timeout-minutes a test holds equal to ci.yml; the "
                                              "harness reads it nowhere (#1146)",
    "harness/ci_budget.py:WARN_SHARE": "when a CI job's time warns; the job runs on either way (#1146)",
    f"{T}:SLOWER_ADDED_S": "which tests a CI run names in a slower-test warning; every test still runs and is timed",
    f"{T}:SLOWER_RATIO": "which tests a CI run names in a slower-test warning; every test still runs and is timed",
}
