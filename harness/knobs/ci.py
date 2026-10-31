"""Knobs of the check-macos CI job: its timeout, its budget warning, and the per-test slowdown it names (#1146)."""
from harness.knobs.base import _k

B = "harness/ci_budget.py"
T = "harness/suite_time.py"

KNOBS = [
    _k("ci_budget_warn", [f"{B}:WARN_SHARE"], [0.7, 0.8, 0.9],
       note="share of its timeout a CI job may use before ci_budget prints a GitHub warning (#1146)"),
    _k("ci_macos_timeout", [f"{B}:MACOS_TIMEOUT_MIN"], [15, 20, 26, 30],
       note="check-macos timeout-minutes: 2x the slowest normal full push run on the 3-vCPU M1 class (12.7 min, "
            "run 40005198738); a slow M1 host ran the same code 2.0x slower (run 40020366592 attempt 1 vs 2); "
            "M2 Pro runs take 4.6-5.1 (#724, #1146)"),
    _k("ci_slower_added", [f"{T}:SLOWER_ADDED_S"], [10.0, 30.0, 60.0],
       note="seconds more than on the last main run a test must take to be named slower; with ci_slower_ratio, "
            "42 ordered pairs of 7 runs named only the two tests #1181 made wait 120 s (#1146)"),
    _k("ci_slower_ratio", [f"{T}:SLOWER_RATIO"], [3.0, 5.0, 8.0],
       note="times its last main run a test must take to be named slower; 3x with 20 s also named two tests "
            "that vary by runner (#1146)"),
]

NEVER_CUTS = {
    "harness/ci_budget.py:MACOS_TIMEOUT_MIN": "a copy of check-macos timeout-minutes a test holds equal to ci.yml; the "
                                              "harness reads it nowhere (#1146)",
    "harness/ci_budget.py:WARN_SHARE": "when a CI job's time warns; the job runs on either way (#1146)",
}
