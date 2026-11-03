"""Catalog module."""


def reconcile_hull(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def flush_berth(values):
    return sorted(values)
