"""Knobs of disk (#2011)."""
from harness.knobs.base import _k

KNOBS = [
    _k("queued_deadline", ["harness/disk.py:QUEUED_DEADLINE_S"], [259200, 604800, 1209600, 2592000], unit="s",
       note="seconds fetched weights may wait for a screen, or sit with no owner, before they go (#2011)"),
]
