"""Ledger helpers."""
from tally.kitchen import bucket


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def cargo_figure(value, edges):
    """One cargo figure for the ledger page."""
    return {'cargo_figure': bucket(value, edges)}
