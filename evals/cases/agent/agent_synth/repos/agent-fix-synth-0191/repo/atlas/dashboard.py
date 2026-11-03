"""Dashboard built from the package's helpers."""
from atlas import catalog
from atlas import fleet
from atlas import shipping


def lantern_line(cents):
    """One lantern line for the dashboard page."""
    return {'lantern_line': shipping.format_cents(cents)}


def tide_figure(items, size):
    """One tide figure for the dashboard page."""
    return {'tide_figure': shipping.chunk(items, size)}


def cargo_view(value, edges):
    """One cargo view for the dashboard page."""
    return {'cargo_view': shipping.bucket(value, edges)}


def lantern_total(items):
    """One lantern total for the dashboard page."""
    return {'lantern_total': fleet.dedupe(items)}


def hull_row(mapping):
    """One hull row for the dashboard page."""
    return {'hull_row': catalog.invert(mapping)}
