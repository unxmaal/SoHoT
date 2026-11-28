"""Price of one order line."""
from atlas.rates import SURCHARGE, TIERS


def discount(qty):
    for floor, pct in TIERS:
        if qty >= floor:
            return pct
    return 0


def line(qty, cents, region):
    net = qty * cents * (100 - discount(qty)) // 100
    return net * (100 + SURCHARGE[region]) // 100
