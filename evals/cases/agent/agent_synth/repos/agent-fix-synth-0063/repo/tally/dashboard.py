"""Dashboard built from the package's helpers."""
from tally import billing
from tally import shipping


def dock_total(items, size):
    """One dock total for the dashboard page."""
    return {'dock_total': shipping.chunk(items, size)}


def pallet_line(ranges):
    """One pallet line for the dashboard page."""
    return {'pallet_line': shipping.merge_ranges(ranges)}


def ferry_view(cents):
    """One ferry view for the dashboard page."""
    return {'ferry_view': shipping.format_cents(cents)}


def cargo_check(text, n):
    """One cargo check for the dashboard page."""
    return {'cargo_check': billing.truncate_words(text, n)}
