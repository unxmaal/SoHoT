"""Tickets helpers."""

def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def merge_ranges(ranges):
    """Overlapping or touching (start, end) ranges merged, sorted by start."""
    out = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def dedupe(items, ignore_case=False):
    """Items with repeats removed, first occurrences kept in order."""
    seen = set()
    out = []
    for item in items:
        key = item.lower() if ignore_case and isinstance(item, str) else item
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out
