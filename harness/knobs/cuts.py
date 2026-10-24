"""Knobs of how a limit that binds records the cut (#1087)."""
from harness.knobs.base import _k

KNOBS = [
    _k("cut_write_wait", ["harness/cuts.py:WRITE_WAIT_S"], [0.05, 0.25, 1.0, 5.0],
       note="seconds a cut written on its own connection waits for the store's lock before it is spooled to "
            "limit_cuts.jsonl for the next write to move (#1087)"),
]

NOT_GATING = {
    f"harness/limit_trace.py:CALLS[{name}]": "the position of the argument naming the knob in that harness.cuts call"
    for name in ("cut", "filled", "take", "timeout")
}

#: Limits that pace work and can never cut it; limit_trace refuses one whose value bounds a slice, a min or a loop.
NEVER_CUTS = {
    "harness/chaos.py:_registry_for.fetch->feeds.fetch(delay)": "seconds between a chaos drill's feed retries",
    "harness/checks/render.py:_remove_tree(delay)": "seconds between attempts to delete a render's profile directory",
    "harness/commands/measure.py:STOP_GRACE_S": "seconds a stopped eval child gets to exit before SIGKILL; the stop already decided",
    "harness/exclusive.py:POLL_SECONDS": "seconds between looks at a held machine lock; the deadline decides the wait",
    "harness/feeds.py:RETRY_DELAY": "base seconds between feed retries; the retry count decides when it gives up",
    "harness/gateway_switch.py:BACKOFF_S": "base seconds between gateway switch attempts; RETRIES decides when it gives up",
    "harness/gateway_switch.py:POLL_S": "seconds between gateway probes; SERVE_WAIT_S and MAX_WAIT_S decide the wait",
    "harness/inspect.py:SIZE_DELAY": "base seconds between size lookups; SIZE_RETRIES decides when it gives up",
    "harness/ramp.py:run(settle_s)": "seconds a memory ramp step settles before it is read",
    "harness/throughput.py:sweep(sample_s)": "seconds between footprint samples during a throughput level",
    "harness/usage.py:FLUSH_S": "seconds the gateway usage writer waits before writing a batch; the queue bound drops rows",
    "harness/vllm.py:served(grace)": "seconds a vLLM server gets to exit before SIGKILL, after its work is done",
    "harness/vllm.py:served(poll)": "seconds between readiness probes; the timeout decides the wait",
    "harness/workqueue.py:CANCEL_GRACE_S": "seconds a cancelled job gets to exit before SIGKILL; the cancel already decided",
    "harness/workqueue.py:environ(LH_QUEUE_POLL)": "seconds between work queue looks for a pending job",
    "harness/workqueue.py:serve(poll)": "seconds between work queue looks for a pending job",
    "scripts/services.sh:SERVICES_SETTLE_S": "seconds services.sh waits for a stopped service to release its port",
}
