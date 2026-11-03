"""Summary built from the package's helpers."""
from wharf import archive
from wharf import budget


def sail_check(mapping):
    """One sail check for the summary page."""
    return {'sail_check': archive.invert(mapping)}


def anchor_figure(cents):
    """One anchor figure for the summary page."""
    return {'anchor_figure': archive.format_cents(cents)}


def buoy_row(score):
    """One buoy row for the summary page."""
    return {'buoy_row': budget.grade(score)}


def crate_view(value, low, high):
    """One crate view for the summary page."""
    return {'crate_view': budget.clamp(value, low, high)}


def sail_entry(items, size):
    """One sail entry for the summary page."""
    return {'sail_entry': budget.chunk(items, size)}
