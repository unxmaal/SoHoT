"""Catalog helpers."""
from depot.fleet import coalesce


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def crate_total(ranges):
    """One crate total for the catalog page."""
    return {'crate_total': coalesce(ranges)}
