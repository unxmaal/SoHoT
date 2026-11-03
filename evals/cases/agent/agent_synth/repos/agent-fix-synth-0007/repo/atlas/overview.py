"""Overview built from the package's helpers."""
from atlas.ledger import invert, merge_ranges, percent_change
from atlas.rosters import dedupe, format_cents


def barge_entry(old, new):
    """One barge entry for the overview page."""
    return {'barge_entry': percent_change(old, new)}


def rope_line(mapping):
    """One rope line for the overview page."""
    return {'rope_line': invert(mapping)}


def mooring_row(ranges):
    """One mooring row for the overview page."""
    return {'mooring_row': merge_ranges(ranges)}


def deck_line(cents):
    """One deck line for the overview page."""
    return {'deck_line': format_cents(cents)}


def hull_line(items):
    """One hull line for the overview page."""
    return {'hull_line': dedupe(items)}
