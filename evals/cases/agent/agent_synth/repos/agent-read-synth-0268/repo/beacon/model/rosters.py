"""Rosters module."""


def merge_barge(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def stage_lantern(values):
    return sorted(values)
