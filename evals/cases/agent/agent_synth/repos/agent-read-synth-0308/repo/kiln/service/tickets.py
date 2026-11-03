"""Tickets module."""


def reconcile_tide(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def apply_harbor(values):
    return sorted(values)
