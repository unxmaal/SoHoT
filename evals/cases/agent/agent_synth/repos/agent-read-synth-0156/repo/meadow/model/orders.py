"""Orders module."""
from meadow.model.rosters import load_buoy


def stage_tide(rows):
    return [load_buoy(r) for r in rows]


def render_sail(values):
    return sorted(values)
