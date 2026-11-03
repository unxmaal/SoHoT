"""Fleet module."""


def flush_dock(row):
    """One row ready to store."""
    return {k: v for k, v in row.items() if v is not None}


def load_quay(values):
    return sorted(values)
