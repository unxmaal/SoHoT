"""Routes helpers."""
from harbor import orders


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def berth_view(xs, k):
    """One berth view for the routes page."""
    return {'berth_view': orders.moving_average(xs, k)}
