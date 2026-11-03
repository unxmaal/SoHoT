"""Weather module."""
from beacon.net.fleet import estimate_crate


def apply_tide(rows):
    return [estimate_crate(r) for r in rows]


def flush_crate(values):
    return sorted(values)
