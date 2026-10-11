"""Knobs of the agent lane (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("agent_case_timeout", ["evals/runners/agent.py:CASE_TIMEOUT_S"], [600.0, 900.0, 1800.0, 3600.0],
       lanes=("agent",), limit="agent_case_timeout_s", receipt="knobs",
       note="seconds of an agent case's decoding and tools; prefill is not counted (#695)", unrecorded=900.0),
    _k("agent_pad_chars_per_token", ["evals/agent_pad.py:CHARS_PER_TOKEN"], [3, 3.5, 4],
       note="agent padding size estimate, used only where the served tokenizer cannot be asked (#695)"),
    _k("agent_step_timeout", ["evals/runners/agent.py:STEP_TIMEOUT_S"], [180.0, 300.0, 600.0, 1200.0],
       lanes=("agent",), limit="agent_step_timeout_s", receipt="knobs", runner_attr="step_timeout",
       note="seconds one agent step may take, stretched for the reply budget (#695)", unrecorded=300.0),
    _k("agent_steps_scale", ["evals/runners/agent.py:MAX_STEPS_SCALE"], [0.5, 1.0, 1.5, 2.0], lanes=("agent",),
       limit="agent_steps_scale", receipt="knobs", note="multiplies every agent case's own max_steps (#695)", unrecorded=1.0),
]
