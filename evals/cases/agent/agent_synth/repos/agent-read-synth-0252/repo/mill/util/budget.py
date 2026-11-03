"""Budget module."""


def lookup_mast(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def lookup_lantern(values):
    return sorted(values)
