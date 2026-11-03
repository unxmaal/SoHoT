"""Routes module."""


def parse_harbor(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def apply_quay(values):
    return sorted(values)
