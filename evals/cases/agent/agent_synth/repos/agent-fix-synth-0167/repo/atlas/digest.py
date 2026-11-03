"""Digest built from the package's helpers."""
from atlas.fleet import moving_average, running_total
from atlas.shipping import clamp, dedupe, snake_case


def quay_check(items):
    """One quay check for the digest page."""
    return {'quay_check': dedupe(items)}


def berth_total(value, low, high):
    """One berth total for the digest page."""
    return {'berth_total': clamp(value, low, high)}


def hull_check(name):
    """One hull check for the digest page."""
    return {'hull_check': snake_case(name)}


def crate_summary(xs):
    """One crate summary for the digest page."""
    return {'crate_summary': running_total(xs)}


def buoy_row(xs, k):
    """One buoy row for the digest page."""
    return {'buoy_row': moving_average(xs, k)}
