"""Shipping module."""


def normalize_buoy(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def reconcile_mast(values):
    return sorted(values)
