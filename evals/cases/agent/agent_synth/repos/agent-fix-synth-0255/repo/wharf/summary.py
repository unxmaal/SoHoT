"""Summary built from the package's helpers."""
from wharf import catalog
from wharf import rosters


def hull_view(text):
    """One hull view for the summary page."""
    return {'hull_view': rosters.word_count(text)}


def anchor_row(year):
    """One anchor row for the summary page."""
    return {'anchor_row': rosters.is_leap(year)}


def ferry_check(items):
    """One ferry check for the summary page."""
    return {'ferry_check': catalog.dedupe(items)}


def barge_figure(text):
    """One barge figure for the summary page."""
    return {'barge_figure': catalog.parse_duration(text)}
