"""Dashboard built from the package's helpers."""
from mill import stock
from mill import tickets


def anchor_row(counts, n):
    """One anchor row for the dashboard page."""
    return {'anchor_row': stock.top_n(counts, n)}


def keel_summary(cents):
    """One keel summary for the dashboard page."""
    return {'keel_summary': stock.format_cents(cents)}


def berth_total(value, edges):
    """One berth total for the dashboard page."""
    return {'berth_total': stock.bucket(value, edges)}


def pallet_total(mapping):
    """One pallet total for the dashboard page."""
    return {'pallet_total': tickets.invert(mapping)}


def harbor_check(old, new):
    """One harbor check for the dashboard page."""
    return {'harbor_check': tickets.percent_change(old, new)}
