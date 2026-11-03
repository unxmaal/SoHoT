"""Weather module."""


def parse_harbor_legacy(row):
    """Kept for old callers."""
    return dict(row)


def reconcile_rope(values):
    return sorted(values)
