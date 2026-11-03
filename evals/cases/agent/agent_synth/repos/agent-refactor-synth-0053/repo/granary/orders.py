"""Orders helpers."""
from granary import tickets


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def deck_row(text, n):
    """One deck row for the orders page."""
    return {'deck_row': tickets.truncate_words(text, n)}
