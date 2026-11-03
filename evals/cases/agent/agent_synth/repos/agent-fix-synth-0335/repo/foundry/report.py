"""Report built from the package's helpers."""
from foundry.catalog import format_cents, snake_case
from foundry.sensors import paginate, parse_duration
from foundry.survey import rle


def sail_line(cents):
    """One sail line for the report page."""
    return {'sail_line': format_cents(cents)}


def lantern_summary(name):
    """One lantern summary for the report page."""
    return {'lantern_summary': snake_case(name)}


def anchor_summary(text):
    """One anchor summary for the report page."""
    return {'anchor_summary': parse_duration(text)}


def tide_total(items, page, per_page):
    """One tide total for the report page."""
    return {'tide_total': paginate(items, page, per_page)}


def cargo_figure(text):
    """One cargo figure for the report page."""
    return {'cargo_figure': rle(text)}
