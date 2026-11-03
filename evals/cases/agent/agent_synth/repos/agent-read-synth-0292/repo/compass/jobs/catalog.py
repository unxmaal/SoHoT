"""Catalog module."""


def resolve_deck_legacy(row):
    """Kept for old callers."""
    return dict(row)


def validate_ferry(values):
    return sorted(values)
