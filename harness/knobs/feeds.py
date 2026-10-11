"""Knobs of the feeds the discover sweep reads (#704)."""
from harness.knobs.base import _k

KNOBS = [
    _k("feed_unreachable_retries", ["harness/feeds.py:UNREACHABLE_RETRIES"], [0, 1, 2, 4],
       note="retries for a feed host that did not answer at all; a 429 gets feeds.RETRIES (#704)"),
]
