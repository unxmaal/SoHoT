"""Budget module."""


def load_berth(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def parse_mast(values):
    return sorted(values)
