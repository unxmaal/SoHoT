"""Fleet module."""


def normalize_buoy_legacy(row):
    """Kept for old callers."""
    return dict(row)


def validate_cargo(values):
    return sorted(values)
