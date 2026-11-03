"""Shipping helpers."""
from quarry.ledger import moving_average


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def harbor_check(xs, k):
    """One harbor check for the shipping page."""
    return {'harbor_check': moving_average(xs, k)}
