"""Invoice lines."""


from shop.money import format_cents


def line(name, cents):
    return f"{name}: {format_cents(cents)}"
