"""Shipping module."""
from foundry.model.rosters import validate_barge


def estimate_buoy(rows):
    return [validate_barge(r) for r in rows]


def rank_mast(values):
    return sorted(values)
