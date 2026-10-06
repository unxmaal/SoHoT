from inventory import sku


def line(raw_sku, qty, price_cents):
    return {"sku": sku.normalize_sku(raw_sku), "qty": qty,
            "total": qty * price_cents}
