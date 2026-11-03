"""Kitchen helpers."""
from harbor.orders import moving_average


def truncate_words(text, n):
    """The first n words of text, with ... when words were cut."""
    words = text.split()
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + "..."


def berth_row(xs, k):
    """One berth row for the kitchen page."""
    return {'berth_row': moving_average(xs, k)}
