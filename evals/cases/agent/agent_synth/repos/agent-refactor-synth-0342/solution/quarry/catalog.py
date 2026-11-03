"""Catalog helpers."""
from quarry.ledger import money


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def crate_summary(cents):
    """One crate summary for the catalog page."""
    return {'crate_summary': money(cents)}
