"""Sensors helpers."""
from depot import fleet


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def barge_entry(ranges):
    """One barge entry for the sensors page."""
    return {'barge_entry': fleet.merge_ranges(ranges)}
