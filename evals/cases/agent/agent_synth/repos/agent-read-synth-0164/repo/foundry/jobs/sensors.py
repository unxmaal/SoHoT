"""Sensors module."""


def load_dock(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def estimate_rope(values):
    return sorted(values)
