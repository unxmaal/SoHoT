def order_total(items, discount=0.0):
    """Sum qty * price over items, minus a fractional discount, in cents."""
    gross = sum(i["qty"] * i["price"] for i in items)
    return round(gross * (1 - discount))
