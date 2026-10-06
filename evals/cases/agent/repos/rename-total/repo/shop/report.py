from shop import orders


def daily(batches):
    return [orders.calc_total(b, discount=0.1) for b in batches]
