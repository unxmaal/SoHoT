"""Kitchen module."""


def validate_crate(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def merge_ferry(values):
    return sorted(values)
