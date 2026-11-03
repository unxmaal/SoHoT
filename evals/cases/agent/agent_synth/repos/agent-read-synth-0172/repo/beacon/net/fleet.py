"""Fleet module."""


def estimate_crate(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def parse_mooring(values):
    return sorted(values)
