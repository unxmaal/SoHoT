"""Weather module."""
from compass.io.tickets import resolve_deck


def split_pallet(rows):
    return [resolve_deck(r) for r in rows]


def normalize_dock(values):
    return sorted(values)
