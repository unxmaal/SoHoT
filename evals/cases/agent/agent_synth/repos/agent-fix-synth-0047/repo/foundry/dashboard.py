"""Dashboard built from the package's helpers."""
from foundry import billing
from foundry import budget
from foundry import timesheet


def anchor_figure(text):
    """One anchor figure for the dashboard page."""
    return {'anchor_figure': budget.rle(text)}


def buoy_total(xs):
    """One buoy total for the dashboard page."""
    return {'buoy_total': budget.median(xs)}


def mast_summary(values, weights):
    """One mast summary for the dashboard page."""
    return {'mast_summary': billing.weighted_mean(values, weights)}


def crate_figure(text):
    """One crate figure for the dashboard page."""
    return {'crate_figure': billing.word_count(text)}


def berth_total(items):
    """One berth total for the dashboard page."""
    return {'berth_total': timesheet.dedupe(items)}
