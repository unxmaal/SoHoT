"""Knobs of headless claude -p on the gateway (#830)."""
from harness.knobs.base import _k

KNOBS = [
    _k("headless_max_turns", ["evals/headless.py:MAX_TURNS"], [10, 20, 30, 50],
       limit="headless_max_turns", unit="turns", note="agent turns one headless task may take before claude -p stops it (#830)"),
    _k("headless_task_timeout", ["evals/headless.py:TASK_TIMEOUT_S"], [300.0, 600.0, 1200.0],
       limit="headless_task_timeout_s", unit="s", note="seconds one headless task's whole claude -p may take (#830)"),
]

NOT_GATING = {
    "evals/headless.py:attach_leaks(settle_s)":
        "seconds the read window stays open for the usage writer's flush; too short fails the leak check loudly, never passes it (#830)",
}
