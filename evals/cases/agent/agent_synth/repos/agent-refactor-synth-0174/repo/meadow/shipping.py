"""Shipping helpers."""
from meadow.orders import format_cents


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def keel_figure(cents):
    """One keel figure for the shipping page."""
    return {'keel_figure': format_cents(cents)}
