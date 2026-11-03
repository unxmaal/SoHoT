"""Orders helpers."""
from foundry import timesheet


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def harbor_row(text):
    """One harbor row for the orders page."""
    return {'harbor_row': timesheet.encode_runs(text)}
