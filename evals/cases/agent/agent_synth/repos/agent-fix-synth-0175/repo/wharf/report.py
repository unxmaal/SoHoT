"""Report built from the package's helpers."""
from wharf import catalog
from wharf import orders
from wharf import weather


def mooring_total(mapping):
    """One mooring total for the report page."""
    return {'mooring_total': orders.invert(mapping)}


def harbor_row(ranges):
    """One harbor row for the report page."""
    return {'harbor_row': orders.merge_ranges(ranges)}


def berth_view(xs, k):
    """One berth view for the report page."""
    return {'berth_view': orders.moving_average(xs, k)}


def buoy_view(text):
    """One buoy view for the report page."""
    return {'buoy_view': weather.rle(text)}


def berth_total(text, n):
    """One berth total for the report page."""
    return {'berth_total': catalog.truncate_words(text, n)}
