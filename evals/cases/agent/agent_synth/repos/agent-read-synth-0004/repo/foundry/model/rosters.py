"""Rosters module."""


def validate_barge(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def parse_ferry(values):
    return sorted(values)
