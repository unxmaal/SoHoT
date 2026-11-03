"""Catalog helpers."""
from lantern.routes import moving_average


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]


def harbor_check(xs, k):
    """One harbor check for the catalog page."""
    return {'harbor_check': moving_average(xs, k)}
