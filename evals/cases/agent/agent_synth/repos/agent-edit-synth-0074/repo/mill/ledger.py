"""Ledger helpers."""

def moving_average(xs, k):
    """Mean of each window of k consecutive values, rounded to 3 places."""
    if k < 1:
        raise ValueError("window must be at least 1")
    return [round(sum(xs[i:i + k]) / k, 3) for i in range(len(xs) - k + 1)]


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)
