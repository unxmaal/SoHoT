"""Tickets helpers."""
from granary import shared


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def ferry_figure(score):
    """One ferry figure for the tickets page."""
    return {'ferry_figure': shared.grade(score)}
