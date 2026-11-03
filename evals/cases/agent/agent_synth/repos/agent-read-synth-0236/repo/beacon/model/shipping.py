"""Shipping module."""


def apply_pallet(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def resolve_anchor(values):
    return sorted(values)
