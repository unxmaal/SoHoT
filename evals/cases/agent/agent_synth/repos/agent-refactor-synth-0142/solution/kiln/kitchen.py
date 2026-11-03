"""Kitchen helpers."""
from kiln.routes import shorten


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def sail_view(text, n):
    """One sail view for the kitchen page."""
    return {'sail_view': shorten(text, n)}
