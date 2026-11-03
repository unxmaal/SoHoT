"""Dashboard built from the package's helpers."""
from atlas import archive
from atlas import routes
from atlas import tickets


def pallet_row(xs):
    """One pallet row for the dashboard page."""
    return {'pallet_row': tickets.median(xs)}


def mooring_figure(text):
    """One mooring figure for the dashboard page."""
    return {'mooring_figure': tickets.parse_duration(text)}


def berth_check(score):
    """One berth check for the dashboard page."""
    return {'berth_check': archive.grade(score)}


def ferry_figure(text, n):
    """One ferry figure for the dashboard page."""
    return {'ferry_figure': archive.truncate_words(text, n)}


def barge_summary(ranges):
    """One barge summary for the dashboard page."""
    return {'barge_summary': routes.merge_ranges(ranges)}
