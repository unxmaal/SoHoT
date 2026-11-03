"""Tickets helpers."""
from quarry.shared import luhn_valid


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]


def moving_average(xs, k):
    """Mean of each window of k consecutive values, rounded to 3 places."""
    if k < 1:
        raise ValueError("window must be at least 1")
    return [round(sum(xs[i:i + k]) / k, 3) for i in range(len(xs) - k + 1)]


def mast_entry(number):
    """One mast entry for the tickets page."""
    return {'mast_entry': luhn_valid(number)}
