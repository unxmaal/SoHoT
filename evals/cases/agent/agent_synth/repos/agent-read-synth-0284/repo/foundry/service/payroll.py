"""Payroll module."""


def allocate_barge(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def split_deck(values):
    return sorted(values)
