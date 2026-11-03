"""Billing module."""


def lookup_harbor(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def load_anchor(values):
    return sorted(values)
