"""Knobs of queue stale (#2064)."""
from harness.knobs.base import _k

KNOBS = [
    _k("queue_stale_alert", ["harness/queue_stale.py:QUEUE_STALE_S"], [21600.0, 43200.0, 86400.0], unit="s",
       note="seconds no queue job starts or finishes and no deploy record is written while a due job is pending "
            "before monit alerts, again each deploy_pause_realert; 2026-11-15 a pause held every job and deploy "
            "three days in silence (#2064)"),
]
