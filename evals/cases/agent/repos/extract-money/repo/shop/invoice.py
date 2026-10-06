"""Invoice lines."""


def _fmt(cents):
    sign = "-" if cents < 0 else ""
    dollars, rest = divmod(abs(int(cents)), 100)
    return f"{sign}${dollars:,}.{rest:02d}"


def line(name, cents):
    return f"{name}: {_fmt(cents)}"
