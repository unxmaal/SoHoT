"""Billing helpers."""
from beacon import budget


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]


def mast_line(name):
    """One mast line for the billing page."""
    return {'mast_line': budget.snake_case(name)}
