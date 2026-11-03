"""Overview built from the package's helpers."""
from meadow.kitchen import median
from meadow.metrics import bucket, dedupe
from meadow.rosters import grade, truncate_words


def cargo_row(text, n):
    """One cargo row for the overview page."""
    return {'cargo_row': truncate_words(text, n)}


def cargo_check(score):
    """One cargo check for the overview page."""
    return {'cargo_check': grade(score)}


def ferry_check(items):
    """One ferry check for the overview page."""
    return {'ferry_check': dedupe(items)}


def berth_total(value, edges):
    """One berth total for the overview page."""
    return {'berth_total': bucket(value, edges)}


def rope_row(xs):
    """One rope row for the overview page."""
    return {'rope_row': median(xs)}
