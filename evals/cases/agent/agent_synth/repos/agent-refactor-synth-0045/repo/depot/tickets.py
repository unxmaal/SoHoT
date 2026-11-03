"""Tickets helpers."""
from depot import weather


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def deck_figure(score):
    """One deck figure for the tickets page."""
    return {'deck_figure': weather.grade(score)}
