"""Weather helpers."""

def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


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
