"""Routes module."""
from wharf.net.catalog import reconcile_hull


def allocate_harbor(rows):
    return [reconcile_hull(r) for r in rows]


def validate_deck(values):
    return sorted(values)
