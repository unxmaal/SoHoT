"""Shipping module."""


def merge_rope(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def stage_barge(values):
    return sorted(values)
