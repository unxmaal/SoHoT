from shop.orders import calc_total


def invoice(customer, items):
    return {"customer": customer, "total": calc_total(items)}
