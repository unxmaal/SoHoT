"""Knobs of reference and needle runners (#751)."""
from harness.knobs.base import REQUEST_LANES, _k

KNOBS = [
    _k("claude_code_timeout", ["evals/runners/claude_code.py:TIMEOUT_S"], [300.0, 600.0, 1200.0, 1800.0],
       lanes=REQUEST_LANES, limit="claude_code_timeout_s", unit="s", receipt="knobs", note="seconds one claude -p reference answer may take (#693)", unrecorded=600.0),
    _k("needle_serve_start", ["harness/needle.py:SERVE_START_S"], [30.0, 60.0, 120.0, 300.0],
       lanes=("decide", "agent"), limit="needle_serve_start_s", unit="s", receipt="knobs", note="seconds needle --serve may take to report its address (#693)", unrecorded=60.0),
]

NEVER_CUTS = {
    "harness/needle.py:Chat.__call__(max_tokens)": "needle takes no reply budget; the parameter only matches "
                                                   "completion.chat and is never read (#693)",
    "harness/needle.py:Server.close->self.proc.wait(timeout)": "grace before a terminated needle server is killed; it "
                                                               "is shutting down either way (#693)",
}

NOT_GATING = {
    "evals/runners/process.py:STDERR_TAIL": "lines of a failed child's stderr kept beside its artifact for a person; "
                                            "no check reads them (#601)",
    "evals/runners/base.py:BaseRunner.failed(seconds)": "how long a failed case took, as reported (#706)",
    "evals/runners/agent.py:AgentRunner.failed(seconds)": "how long a failed case took, as reported (#706)",
    **{f"evals/runners/chain.py:STAGE_SCALE[{s}]": "the factor a chain stage multiplies the image size by, a fact of "
       "the stage (#692)" for s in ("upscale-seedvr2", "upscale-controlnet", "controlnet")},
}
