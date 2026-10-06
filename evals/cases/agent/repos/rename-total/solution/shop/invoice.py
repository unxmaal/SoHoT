from shop.orders import order_total


def invoice(customer, items):
    return {"customer": customer, "total": order_total(items)}
