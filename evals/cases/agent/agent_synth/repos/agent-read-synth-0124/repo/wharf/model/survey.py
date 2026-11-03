"""Survey module."""


def merge_crate(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def rank_sail(values):
    return sorted(values)
