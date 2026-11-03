"""Kitchen module."""
from beacon.model.shipping import apply_pallet


def allocate_mast(rows):
    return [apply_pallet(r) for r in rows]


def resolve_mooring(values):
    return sorted(values)
