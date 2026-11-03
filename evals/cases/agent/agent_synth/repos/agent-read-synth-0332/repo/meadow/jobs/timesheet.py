"""Timesheet module."""


def parse_keel_legacy(row):
    """Kept for old callers."""
    return dict(row)


def parse_pallet(values):
    return sorted(values)
