"""Catalog module."""


def parse_berth_legacy(row):
    """Kept for old callers."""
    return dict(row)


def resolve_hull(values):
    return sorted(values)
