"""Fleet module."""
from beacon.io.tickets import rank_dock


def flush_mooring(rows):
    return [rank_dock(r) for r in rows]


def validate_tide(values):
    return sorted(values)
