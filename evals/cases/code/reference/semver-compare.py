def compare(a, b):
    def key(v):
        v = v.split("+", 1)[0]
        core, _, pre = v.partition("-")
        nums = tuple(int(x) for x in core.split("."))
        return nums, (pre.split(".") if pre else [])

    def ident(x, y):
        xd, yd = x.isdigit(), y.isdigit()
        if xd and yd:
            return (int(x) > int(y)) - (int(x) < int(y))
        if xd != yd:
            return -1 if xd else 1
        return (x > y) - (x < y)

    (na, pa), (nb, pb) = key(a), key(b)
    if na != nb:
        return -1 if na < nb else 1
    if not pa or not pb:
        return (not pa) - (not pb)
    for x, y in zip(pa, pb):
        c = ident(x, y)
        if c:
            return c
    return (len(pa) > len(pb)) - (len(pa) < len(pb))
