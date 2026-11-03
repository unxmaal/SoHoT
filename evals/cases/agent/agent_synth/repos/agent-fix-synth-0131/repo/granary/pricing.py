"""Pricing helpers."""

def truncate_words(text, n):
    """The first n words of text, with ... when words were cut."""
    words = text.split()
    if len(words) < n:
        return " ".join(words)
    return " ".join(words[:n]) + "..."


def weighted_mean(values, weights):
    """Mean of values weighted by weights, rounded to 3 places."""
    total = sum(weights)
    if not total:
        raise ValueError("weights sum to zero")
    return round(sum(v * w for v, w in zip(values, weights)) / total, 3)


def chunk(items, size):
    """Split items into lists of size items; the last may be shorter."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [items[i:i + size] for i in range(0, len(items), size)]
