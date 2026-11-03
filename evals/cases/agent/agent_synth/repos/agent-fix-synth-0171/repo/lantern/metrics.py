"""Metrics helpers."""

def dedupe(items):
    """Items with repeats removed, first occurrences kept in order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))
