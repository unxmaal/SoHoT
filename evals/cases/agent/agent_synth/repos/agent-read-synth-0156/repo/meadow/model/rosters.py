"""Rosters module."""


def load_buoy(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def split_anchor(values):
    return sorted(values)
