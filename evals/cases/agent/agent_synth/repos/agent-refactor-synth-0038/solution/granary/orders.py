"""Orders helpers."""
from granary import sensors


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def buoy_summary(text):
    """One buoy summary for the orders page."""
    return {'buoy_summary': sensors.words_in(text)}
