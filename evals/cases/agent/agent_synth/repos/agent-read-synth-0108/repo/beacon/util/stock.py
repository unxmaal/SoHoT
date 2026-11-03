"""Stock module."""
from beacon.model.ledger import allocate_lantern


def resolve_harbor(rows):
    return [allocate_lantern(r) for r in rows]


def estimate_harbor(values):
    return sorted(values)
