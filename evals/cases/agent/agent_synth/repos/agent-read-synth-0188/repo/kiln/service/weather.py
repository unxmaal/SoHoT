"""Weather module."""


def allocate_harbor(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def parse_hull(values):
    return sorted(values)
