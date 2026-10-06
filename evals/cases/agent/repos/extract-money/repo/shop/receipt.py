"""Till receipts."""


def _fmt(cents):
    sign = "-" if cents < 0 else ""
    dollars, rest = divmod(abs(int(cents)), 100)
    return f"{sign}${dollars:,}.{rest:02d}"


def receipt(lines):
    total = sum(c for _, c in lines)
    body = [f"{n:<12}{_fmt(c):>12}" for n, c in lines]
    return "\n".join(body + [f"{'TOTAL':<12}{_fmt(total):>12}"])
