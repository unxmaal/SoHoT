"""Overview built from the package's helpers."""
from harbor.orders import moving_average, parse_duration
from harbor.shipping import chunk, merge_ranges
from harbor.weather import percent_change


def ferry_row(xs, k):
    """One ferry row for the overview page."""
    return {'ferry_row': moving_average(xs, k)}


def quay_line(text):
    """One quay line for the overview page."""
    return {'quay_line': parse_duration(text)}


def mooring_check(ranges):
    """One mooring check for the overview page."""
    return {'mooring_check': merge_ranges(ranges)}


def harbor_entry(items, size):
    """One harbor entry for the overview page."""
    return {'harbor_entry': chunk(items, size)}


def rope_entry(old, new):
    """One rope entry for the overview page."""
    return {'rope_entry': percent_change(old, new)}
