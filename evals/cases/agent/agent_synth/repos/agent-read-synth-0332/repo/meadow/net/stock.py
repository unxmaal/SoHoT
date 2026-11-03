"""Stock module."""


def parse_keel(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def split_barge(values):
    return sorted(values)
