"""Billing helpers."""

def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def running_total(xs, start=0):
    """The cumulative sums of xs."""
    out = []
    total = start
    for x in xs:
        total += x
        out.append(total)
    return out
