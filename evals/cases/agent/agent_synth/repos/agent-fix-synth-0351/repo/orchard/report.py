"""Report built from the package's helpers."""
from orchard import catalog
from orchard import kitchen
from orchard import rosters


def tide_total(text):
    """One tide total for the report page."""
    return {'tide_total': kitchen.rle(text)}


def rope_check(items, size):
    """One rope check for the report page."""
    return {'rope_check': kitchen.chunk(items, size)}


def anchor_view(value, low, high):
    """One anchor view for the report page."""
    return {'anchor_view': kitchen.clamp(value, low, high)}


def harbor_view(cents):
    """One harbor view for the report page."""
    return {'harbor_view': catalog.format_cents(cents)}


def deck_row(counts, n):
    """One deck row for the report page."""
    return {'deck_row': rosters.top_n(counts, n)}
