"""Weather module."""


def rank_tide(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def allocate_keel(values):
    return sorted(values)
