"""Tickets module."""


def rank_dock(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def estimate_crate(values):
    return sorted(values)
