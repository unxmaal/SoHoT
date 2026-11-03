"""Fleet module."""
from wharf.model.survey import merge_crate


def normalize_dock(rows):
    return [merge_crate(r) for r in rows]


def stage_tide(values):
    return sorted(values)
