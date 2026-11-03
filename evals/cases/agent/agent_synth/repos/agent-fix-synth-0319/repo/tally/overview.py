"""Overview built from the package's helpers."""
from tally.billing import grade, parse_duration
from tally.catalog import invert
from tally.orders import rle, running_total


def ferry_figure(xs):
    """One ferry figure for the overview page."""
    return {'ferry_figure': running_total(xs)}


def deck_figure(text):
    """One deck figure for the overview page."""
    return {'deck_figure': rle(text)}


def mast_summary(text):
    """One mast summary for the overview page."""
    return {'mast_summary': parse_duration(text)}


def deck_view(score):
    """One deck view for the overview page."""
    return {'deck_view': grade(score)}


def quay_line(mapping):
    """One quay line for the overview page."""
    return {'quay_line': invert(mapping)}
