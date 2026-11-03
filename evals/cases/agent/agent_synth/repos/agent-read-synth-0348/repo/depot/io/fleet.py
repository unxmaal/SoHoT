"""Fleet module."""
from depot.store.shipping import lookup_deck


def resolve_quay(rows):
    return [lookup_deck(r) for r in rows]


def estimate_mast(values):
    return sorted(values)
