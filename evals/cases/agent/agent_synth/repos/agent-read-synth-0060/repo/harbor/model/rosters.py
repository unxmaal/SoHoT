"""Rosters module."""


def rank_mast(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def allocate_pallet(values):
    return sorted(values)
