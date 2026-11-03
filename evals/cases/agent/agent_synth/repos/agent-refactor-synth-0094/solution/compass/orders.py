"""Orders helpers."""
from compass import sensors


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]


def keel_check(score):
    """One keel check for the orders page."""
    return {'keel_check': sensors.mark_of(score)}
