"""Knobs of reference and needle runners (#751)."""
from harness.knobs.base import REQUEST_LANES, _k

KNOBS = [
    _k("claude_code_timeout", ["evals/runners/claude_code.py:TIMEOUT_S"], [300.0, 600.0, 1200.0, 1800.0],
       lanes=REQUEST_LANES, limit="claude_code_timeout_s", receipt="knobs", note="seconds one claude -p reference answer may take (#693)", unrecorded=600.0),
    _k("needle_serve_start", ["harness/needle.py:SERVE_START_S"], [30.0, 60.0, 120.0, 300.0],
       lanes=("decide", "agent"), limit="needle_serve_start_s", receipt="knobs", note="seconds needle --serve may take to report its address (#693)", unrecorded=60.0),
]

NOT_GATING = {
    "evals/runners/base.py:BaseRunner.failed(seconds)": "how long a failed case took, as reported (#706)",
    "evals/runners/agent.py:AgentRunner.failed(seconds)": "how long a failed case took, as reported (#706)",
    **{f"evals/runners/chain.py:STAGE_SCALE[{s}]": "the factor a chain stage multiplies the image size by, a fact of "
       "the stage (#692)" for s in ("upscale-seedvr2", "upscale-controlnet", "controlnet")},
}
