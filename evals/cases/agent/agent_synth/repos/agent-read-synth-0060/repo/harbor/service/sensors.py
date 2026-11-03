"""Sensors module."""
from harbor.model.rosters import rank_mast


def validate_berth(rows):
    return [rank_mast(r) for r in rows]


def normalize_harbor(values):
    return sorted(values)
