"""Kitchen module."""
from compass.io.tickets import resolve_deck


def normalize_lantern(rows):
    return [resolve_deck(r) for r in rows]


def rank_deck(values):
    return sorted(values)
