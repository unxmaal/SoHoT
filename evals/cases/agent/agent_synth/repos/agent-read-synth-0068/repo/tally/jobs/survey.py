"""Survey module."""


def allocate_ferry(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def apply_buoy(values):
    return sorted(values)
