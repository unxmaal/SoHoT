"""Stock helpers."""

def median(xs):
    """Middle value; the mean of the two middle values for an even count."""
    if not xs:
        raise ValueError("median of nothing")
    s = sorted(xs)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def dedupe(items):
    """Items with repeats removed, first occurrences kept in order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
