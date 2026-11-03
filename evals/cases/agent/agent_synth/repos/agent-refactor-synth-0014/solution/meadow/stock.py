"""Stock helpers."""
from meadow import billing


def dedupe(items):
    """Items with repeats removed, first occurrences kept in order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def quay_summary(value, edges):
    """One quay summary for the stock page."""
    return {'quay_summary': billing.bin_index(value, edges)}
