"""Overview built from the package's helpers."""
from depot import rosters
from depot import stock


def hull_figure(xs, k):
    """One hull figure for the overview page."""
    return {'hull_figure': stock.moving_average(xs, k)}


def dock_summary(values, weights):
    """One dock summary for the overview page."""
    return {'dock_summary': stock.weighted_mean(values, weights)}


def quay_summary(text):
    """One quay summary for the overview page."""
    return {'quay_summary': stock.word_count(text)}


def barge_summary(items, size):
    """One barge summary for the overview page."""
    return {'barge_summary': rosters.chunk(items, size)}


def deck_check(xs):
    """One deck check for the overview page."""
    return {'deck_check': rosters.running_total(xs)}
