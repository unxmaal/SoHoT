"""Knobs of disk (#2011)."""
from harness.knobs.base import _k

KNOBS = [
    _k("unowned_deadline", ["harness/disk.py:UNOWNED_DEADLINE_S"], [259200, 604800, 1209600, 2592000], unit="s",
       note="seconds recorded weights with no owner, verdict or dependent stay after their download (#2011)"),
]
