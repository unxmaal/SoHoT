"""Weather helpers."""

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
