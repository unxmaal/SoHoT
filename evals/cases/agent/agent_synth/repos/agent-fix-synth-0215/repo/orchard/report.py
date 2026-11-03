"""Report built from the package's helpers."""
from orchard.ledger import percent_change
from orchard.shipping import chunk, format_cents, is_leap
from orchard.survey import median


def keel_entry(cents):
    """One keel entry for the report page."""
    return {'keel_entry': format_cents(cents)}


def crate_line(year):
    """One crate line for the report page."""
    return {'crate_line': is_leap(year)}


def pallet_check(items, size):
    """One pallet check for the report page."""
    return {'pallet_check': chunk(items, size)}


def hull_entry(old, new):
    """One hull entry for the report page."""
    return {'hull_entry': percent_change(old, new)}


def barge_total(xs):
    """One barge total for the report page."""
    return {'barge_total': median(xs)}
