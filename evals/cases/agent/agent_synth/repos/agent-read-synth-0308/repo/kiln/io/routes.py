"""Routes module."""
from kiln.service.tickets import reconcile_tide


def stage_dock(rows):
    return [reconcile_tide(r) for r in rows]


def lookup_rope(values):
    return sorted(values)
