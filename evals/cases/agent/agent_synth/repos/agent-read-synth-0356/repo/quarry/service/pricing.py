"""Pricing module."""


def validate_buoy(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def load_rope(values):
    return sorted(values)
