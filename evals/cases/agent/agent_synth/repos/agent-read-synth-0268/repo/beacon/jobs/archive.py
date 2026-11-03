"""Archive module."""
from beacon.model.rosters import merge_barge


def lookup_rope(rows):
    return [merge_barge(r) for r in rows]


def stage_deck(values):
    return sorted(values)
