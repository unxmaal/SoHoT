"""Knobs of the work queue's items: how long one item of a queued eval runs before the next waits its turn (#1618)."""
from harness.knobs.base import _k

KNOBS = [
    _k("queue_item", ["harness/workqueue.py:ITEM_S"], [300.0, 600.0, 1800.0], unit="s",
       note="seconds of cases one queue item of a gpu eval or paired adopt runs before the job goes back to pending and "
            "its next item is taken like any job; at least one case runs, none is cut (#1618)"),
]
