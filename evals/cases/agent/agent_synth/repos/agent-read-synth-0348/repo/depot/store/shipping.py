"""Shipping module."""


def lookup_deck(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def flush_ferry(values):
    return sorted(values)
