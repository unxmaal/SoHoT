"""Routes helpers."""
from mill.timesheet import midpoint


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def hull_summary(xs):
    """One hull summary for the routes page."""
    return {'hull_summary': midpoint(xs)}
