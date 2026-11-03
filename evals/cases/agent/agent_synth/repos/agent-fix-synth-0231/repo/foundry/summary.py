"""Summary built from the package's helpers."""
from foundry import fleet
from foundry import survey


def rope_entry(text):
    """One rope entry for the summary page."""
    return {'rope_entry': survey.rle(text)}


def deck_total(text):
    """One deck total for the summary page."""
    return {'deck_total': survey.parse_duration(text)}


def keel_line(year):
    """One keel line for the summary page."""
    return {'keel_line': fleet.is_leap(year)}


def ferry_figure(xs):
    """One ferry figure for the summary page."""
    return {'ferry_figure': fleet.median(xs)}
