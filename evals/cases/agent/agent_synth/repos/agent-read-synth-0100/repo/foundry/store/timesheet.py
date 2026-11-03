"""Timesheet module."""


def validate_lantern(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def apply_rope(values):
    return sorted(values)
