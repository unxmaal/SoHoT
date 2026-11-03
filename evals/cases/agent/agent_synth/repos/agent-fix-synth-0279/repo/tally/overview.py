"""Overview built from the package's helpers."""
from tally import orders
from tally import rosters


def quay_line(values, weights):
    """One quay line for the overview page."""
    return {'quay_line': orders.weighted_mean(values, weights)}


def rope_total(mapping):
    """One rope total for the overview page."""
    return {'rope_total': orders.invert(mapping)}


def dock_total(text):
    """One dock total for the overview page."""
    return {'dock_total': orders.parse_duration(text)}


def rope_row(cents):
    """One rope row for the overview page."""
    return {'rope_row': rosters.format_cents(cents)}
