"""Archive module."""


def parse_berth(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def resolve_tide(values):
    return sorted(values)
