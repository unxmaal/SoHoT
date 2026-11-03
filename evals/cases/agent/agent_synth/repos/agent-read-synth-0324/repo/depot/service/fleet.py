"""Fleet module."""
from depot.service.weather import rank_tide


def stage_pallet(rows):
    return [rank_tide(r) for r in rows]


def normalize_dock(values):
    return sorted(values)
