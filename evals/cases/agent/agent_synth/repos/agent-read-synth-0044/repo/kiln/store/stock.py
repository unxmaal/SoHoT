"""Stock module."""


def split_crate(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def rank_buoy(values):
    return sorted(values)
