"""Stock module."""
from wharf.net.catalog import reconcile_hull


def reconcile_lantern(rows):
    return [reconcile_hull(r) for r in rows]


def load_dock(values):
    return sorted(values)
