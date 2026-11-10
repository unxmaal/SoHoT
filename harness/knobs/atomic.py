"""Knobs of `soh atomic`: decomposed repo cases with hidden checks (#1690)."""
from harness.knobs.base import _k

KNOBS = [
    _k("atomic_attempts", ["evals/atomic.py:ATTEMPTS"], [1, 2, 3, 5],
       note="fresh local attempts per case before it goes to the cloud (#1690)"),
    _k("atomic_local_max_tokens", ["evals/atomic.py:LOCAL_MAX_TOKENS"], [8192, 16384, 24576], unit="tokens",
       note="reply budget of one local subtask call, reasoning included; cut to what the served context leaves (#1690)"),
    _k("atomic_min_reply_tokens", ["evals/atomic.py:MIN_REPLY_TOKENS"], [1024, 2048, 4096], unit="tokens",
       note="the smallest reply budget a subtask call is retried at; below it the attempt fails (#1690)"),
    _k("atomic_plan_timeout_s", ["evals/atomic.py:PLAN_TIMEOUT_S"], [300, 900, 1800], unit="s",
       note="how long one claude -p planning call may take before the case goes to the cloud answer (#1690)"),
]

NOT_GATING = {
    "evals/atomic.py:REPLY_TAIL": "characters of a failed reply kept in the case record for audit; the attempt has "
                                  "already failed when it is cut (#1690)",
    "evals/atomic.py:lock_holders->run(timeout)": "how long lsof may take to list the lock's holders; it reads, and a "
                                                  "failure is reported as a holder, so the run stops (#1690)",
}
