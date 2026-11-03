"""Stock module."""


def rank_sail(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def allocate_sail(values):
    return sorted(values)
