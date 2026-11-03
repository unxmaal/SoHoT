"""Sensors module."""


def lookup_ferry(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def load_crate(values):
    return sorted(values)
