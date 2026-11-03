"""Budget module."""
from beacon.service.shipping import normalize_buoy


def validate_barge(rows):
    return [normalize_buoy(r) for r in rows]


def split_mast(values):
    return sorted(values)
