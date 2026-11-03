"""Weather module."""


def parse_buoy_legacy(row):
    """Kept for old callers."""
    return dict(row)


def parse_anchor(values):
    return sorted(values)
