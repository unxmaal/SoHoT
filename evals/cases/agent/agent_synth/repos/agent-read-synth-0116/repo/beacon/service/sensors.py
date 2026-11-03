"""Sensors module."""


def load_berth_legacy(row):
    """Kept for old callers."""
    return dict(row)


def load_crate(values):
    return sorted(values)
