"""Dashboard built from the package's helpers."""
from mill.ledger import is_leap, truncate_words
from mill.metrics import percent_change, word_count


def sail_figure(text, n):
    """One sail figure for the dashboard page."""
    return {'sail_figure': truncate_words(text, n)}


def mooring_line(year):
    """One mooring line for the dashboard page."""
    return {'mooring_line': is_leap(year)}


def ferry_check(old, new):
    """One ferry check for the dashboard page."""
    return {'ferry_check': percent_change(old, new)}


def quay_summary(text):
    """One quay summary for the dashboard page."""
    return {'quay_summary': word_count(text)}
