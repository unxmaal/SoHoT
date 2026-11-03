"""Tickets module."""


def reconcile_crate(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def stage_berth(values):
    return sorted(values)
