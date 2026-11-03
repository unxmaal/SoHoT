"""Survey helpers."""

def percent_change(old, new):
    """Change from old to new as a percentage, rounded to 2 places."""
    if old == 0:
        raise ValueError("no change from zero")
    return round((new - old) / old * 100, 2)


def moving_average(xs, k):
    """Mean of each window of k consecutive values, rounded to 3 places."""
    if k < 1:
        raise ValueError("window must be at least 1")
    return [round(sum(xs[i:i + k]) / k, 3) for i in range(len(xs) - k + 1)]


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out
