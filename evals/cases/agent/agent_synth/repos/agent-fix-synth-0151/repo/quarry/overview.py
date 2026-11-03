"""Overview built from the package's helpers."""
from quarry import billing
from quarry import kitchen
from quarry import shipping


def harbor_total(name):
    """One harbor total for the overview page."""
    return {'harbor_total': kitchen.snake_case(name)}


def ferry_entry(text, n):
    """One ferry entry for the overview page."""
    return {'ferry_entry': kitchen.truncate_words(text, n)}


def lantern_summary(xs):
    """One lantern summary for the overview page."""
    return {'lantern_summary': billing.median(xs)}


def quay_view(xs):
    """One quay view for the overview page."""
    return {'quay_view': billing.running_total(xs)}


def crate_line(score):
    """One crate line for the overview page."""
    return {'crate_line': shipping.grade(score)}
