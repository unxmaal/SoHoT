"""Weather module."""
from beacon.net.tickets import reconcile_crate


def stage_keel(rows):
    return [reconcile_crate(r) for r in rows]


def apply_pallet(values):
    return sorted(values)
