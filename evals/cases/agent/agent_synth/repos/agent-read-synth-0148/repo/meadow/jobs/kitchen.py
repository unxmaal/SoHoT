"""Kitchen module."""
from meadow.store.tickets import reconcile_sail


def flush_mooring(rows):
    return [reconcile_sail(r) for r in rows]


def apply_lantern(values):
    return sorted(values)
