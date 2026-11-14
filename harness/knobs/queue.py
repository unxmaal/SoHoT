"""Knobs of the work queue's items: how long one item of a queued eval runs before the next waits its turn (#1618)."""
from harness.knobs.base import _k

KNOBS = [
    _k("job_pause_expiry", ["harness/paused_jobs.py:EXPIRY_S"], [21600.0, 86400.0, 172800.0], unit="s",
       note="seconds a paused queue job waits for its pause's cause to clear before it fails expired with one alert (#1764)"),
    _k("memory_wait_named", ["harness/memory_wait.py:LONG_S"], [3600.0, 21600.0, 86400.0], unit="s",
       note="seconds a pending gpu job may wait on memory admission before soh morning and soh jobs list name it with what it needs, what is admissible now and what holds the rest; job 1624 waited 94 h unseen (#1993)"),
    _k("queue_item", ["harness/workqueue.py:ITEM_S"], [300.0, 600.0, 1800.0], unit="s",
       note="seconds of cases one queue item of a gpu eval or paired adopt runs before the job goes back to pending and "
            "its next item is taken like any job; at least one case runs, none is cut (#1618)"),
    _k("queue_quiesce_timeout", ["harness/quiesce.py:QUIESCE_TIMEOUT_S"], [600.0, 1800.0, 3600.0], unit="s",
       note="seconds an install or volume stop waits, the queue paused, for the running job to end before it gives up "
            "not-quiesced (worker not reloaded, one alert); below deploy_install_timeout so the install says why (#1762)"),
]

NOT_GATING = {
    "harness/job_claim.py:await_pid(poll)": "seconds between looks for the pid of a job its worker is starting; the "
                                            "caller's wait bounds the wait, this only paces it (#1895)",
    "harness/quiesce.py:quiesce(wait)": "seconds between looks for a running job while the queue is paused; "
                                        "queue_quiesce_timeout bounds the wait, this only paces it (#577, #1762)",
}
