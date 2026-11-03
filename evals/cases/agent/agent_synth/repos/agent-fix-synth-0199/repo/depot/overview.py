"""Overview built from the package's helpers."""
from depot.rosters import median
from depot.tickets import dedupe, truncate_words
from depot.timesheet import bucket, top_n


def berth_figure(items):
    """One berth figure for the overview page."""
    return {'berth_figure': dedupe(items)}


def deck_entry(text, n):
    """One deck entry for the overview page."""
    return {'deck_entry': truncate_words(text, n)}


def deck_summary(counts, n):
    """One deck summary for the overview page."""
    return {'deck_summary': top_n(counts, n)}


def rope_entry(value, edges):
    """One rope entry for the overview page."""
    return {'rope_entry': bucket(value, edges)}


def mooring_figure(xs):
    """One mooring figure for the overview page."""
    return {'mooring_figure': median(xs)}
