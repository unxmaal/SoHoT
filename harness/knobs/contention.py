"""Knobs of the contention gate GPU jobs and deploys wait for, in place of the night rule (#1509)."""
from harness.knobs.base import _k

KNOBS = [
    _k("contention_idle", ["harness/contention.py:IDLE_S"], [300.0, 600.0, 900.0, 1800.0], unit="s",
       note="seconds the served lanes must go with no client request (purpose work or unknown) before a GPU job or "
            "deploy starts; a client served since a batch GPU job started pauses it. Store 2026-11-07, 14 d: 2090 "
            "client requests, gaps p50 0.7 s, p99 182 s; at 600 s they form 14 bursts and hold GPU work 0.34 h/day "
            "(0.25 at 300 s, 0.61 at 1800 s) (#1509)"),
]
