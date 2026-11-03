"""Stock module."""


def merge_pallet(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def validate_berth(values):
    return sorted(values)
