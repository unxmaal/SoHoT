"""Archive helpers."""

def running_total(xs, start=0):
    """The cumulative sums of xs."""
    out = []
    total = start
    for x in xs:
        total += x
        out.append(total)
    return out


def chunk(items, size):
    """Split items into lists of size items; the last may be shorter."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [items[i:i + size] for i in range(0, len(items), size)]


def truncate_words(text, n):
    """The first n words of text, with ... when words were cut."""
    words = text.split()
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + "..."
