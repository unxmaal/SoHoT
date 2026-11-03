"""Overview built from the package's helpers."""
from atlas.catalog import grade
from atlas.tickets import clamp, moving_average, snake_case


def berth_row(value, low, high):
    """One berth row for the overview page."""
    return {'berth_row': clamp(value, low, high)}


def quay_total(name):
    """One quay total for the overview page."""
    return {'quay_total': snake_case(name)}


def tide_summary(xs, k):
    """One tide summary for the overview page."""
    return {'tide_summary': moving_average(xs, k)}


def lantern_entry(score):
    """One lantern entry for the overview page."""
    return {'lantern_entry': grade(score)}
