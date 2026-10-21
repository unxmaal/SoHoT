"""Knobs of the feeds and registries the discover sweep reads (#704)."""
from harness.knobs.base import _k

KNOBS = [
    _k("feed_unreachable_retries", ["harness/feeds.py:UNREACHABLE_RETRIES"], [0, 1, 2, 4],
       note="retries for a feed host that did not answer at all; a 429 gets feeds.RETRIES (#704)"),
    _k("ratelimit_attempts", ["harness/ratelimit.py:ATTEMPTS"], [2, 3, 5, 8],
       note="GETs an upstream answering 429 gets before the caller defers the rest of its batch (#630, #1085)"),
]
