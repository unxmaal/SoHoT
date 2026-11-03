"""Timesheet helpers."""

def median(xs):
    """Middle value; the mean of the two middle values for an even count."""
    if not xs:
        raise ValueError("median of nothing")
    s = sorted(xs)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def truncate_words(text, n):
    """The first n words of text, with ... when words were cut."""
    words = text.split()
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + "..."


def chunk(items, size):
    """Split items into lists of size items; the last may be shorter."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [items[i:i + size] for i in range(0, len(items), size)]
