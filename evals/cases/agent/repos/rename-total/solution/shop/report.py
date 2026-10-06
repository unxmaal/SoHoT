from shop import orders


def daily(batches):
    return [orders.order_total(b, discount=0.1) for b in batches]
