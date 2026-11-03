"""Overview built from the package's helpers."""
from tally.sensors import clamp, truncate_words
from tally.tickets import moving_average
from tally.weather import merge_ranges, paginate


def mast_total(items, page, per_page):
    """One mast total for the overview page."""
    return {'mast_total': paginate(items, page, per_page)}


def crate_line(ranges):
    """One crate line for the overview page."""
    return {'crate_line': merge_ranges(ranges)}


def anchor_figure(value, low, high):
    """One anchor figure for the overview page."""
    return {'anchor_figure': clamp(value, low, high)}


def ferry_view(text, n):
    """One ferry view for the overview page."""
    return {'ferry_view': truncate_words(text, n)}


def sail_entry(xs, k):
    """One sail entry for the overview page."""
    return {'sail_entry': moving_average(xs, k)}
