"""Weather module."""
from beacon.net.fleet import stage_cargo


def merge_rope(rows):
    return [stage_cargo(r) for r in rows]


def rank_barge(values):
    return sorted(values)
