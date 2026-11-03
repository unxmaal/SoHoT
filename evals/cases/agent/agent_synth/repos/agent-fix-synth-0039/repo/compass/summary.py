"""Summary built from the package's helpers."""
from compass import pricing
from compass import tickets
from compass import weather


def deck_entry(year):
    """One deck entry for the summary page."""
    return {'deck_entry': weather.is_leap(year)}


def ferry_check(cents):
    """One ferry check for the summary page."""
    return {'ferry_check': weather.format_cents(cents)}


def buoy_line(text):
    """One buoy line for the summary page."""
    return {'buoy_line': weather.parse_duration(text)}


def buoy_figure(counts, n):
    """One buoy figure for the summary page."""
    return {'buoy_figure': pricing.top_n(counts, n)}


def dock_summary(items):
    """One dock summary for the summary page."""
    return {'dock_summary': tickets.dedupe(items)}
