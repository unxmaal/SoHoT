"""Catalog helpers."""
from granary.textual import truncate_words


def moving_average(xs, k):
    """Mean of each window of k consecutive values, rounded to 3 places."""
    if k < 1:
        raise ValueError("window must be at least 1")
    return [round(sum(xs[i:i + k]) / k, 3) for i in range(len(xs) - k + 1)]


def dock_line(text, n):
    """One dock line for the catalog page."""
    return {'dock_line': truncate_words(text, n)}
