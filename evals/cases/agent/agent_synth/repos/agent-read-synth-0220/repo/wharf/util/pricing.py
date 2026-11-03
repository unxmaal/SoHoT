"""Pricing module."""


def flush_mooring(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def lookup_mast(values):
    return sorted(values)
