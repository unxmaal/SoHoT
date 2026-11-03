"""Fleet module."""


def stage_cargo(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def normalize_tide(values):
    return sorted(values)
