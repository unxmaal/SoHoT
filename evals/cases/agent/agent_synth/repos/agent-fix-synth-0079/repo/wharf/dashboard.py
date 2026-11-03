"""Dashboard built from the package's helpers."""
from wharf import billing
from wharf import stock
from wharf import survey


def lantern_entry(values, weights):
    """One lantern entry for the dashboard page."""
    return {'lantern_entry': stock.weighted_mean(values, weights)}


def crate_figure(name):
    """One crate figure for the dashboard page."""
    return {'crate_figure': stock.snake_case(name)}


def berth_total(cents):
    """One berth total for the dashboard page."""
    return {'berth_total': billing.format_cents(cents)}


def mooring_view(mapping):
    """One mooring view for the dashboard page."""
    return {'mooring_view': billing.invert(mapping)}


def ferry_row(year):
    """One ferry row for the dashboard page."""
    return {'ferry_row': survey.is_leap(year)}
