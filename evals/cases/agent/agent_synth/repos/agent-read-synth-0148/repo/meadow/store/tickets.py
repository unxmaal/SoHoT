"""Tickets module."""


def reconcile_sail(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def flush_pallet(values):
    return sorted(values)
