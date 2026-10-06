from inventory.sku import normalize_sku

_STOCK = {}


def add(sku, qty):
    key = normalize_sku(sku)
    _STOCK[key] = _STOCK.get(key, 0) + qty
    return _STOCK[key]
