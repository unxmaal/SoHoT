"""Stock helpers."""
from granary import catalog


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def dedupe(items):
    """Items with repeats removed, first occurrences kept in order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def mast_summary(value, edges):
    """One mast summary for the stock page."""
    return {'mast_summary': catalog.bucket(value, edges)}
