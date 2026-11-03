"""Sensors helpers."""

def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def dedupe(items):
    """Items with repeats removed, first occurrences kept in order."""
    return sorted(set(items))


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]
