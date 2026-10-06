_VALUES = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
           (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
           (5, "V"), (4, "IV"), (1, "I")]


def to_roman(n):
    if not isinstance(n, int) or not 1 <= n <= 3999:
        raise ValueError(n)
    out = []
    for value, glyph in _VALUES:
        while n >= value:
            out.append(glyph)
            n -= value
    return "".join(out)


def from_roman(s):
    if not isinstance(s, str) or not s:
        raise ValueError(s)
    total, i = 0, 0
    for value, glyph in _VALUES:
        while s.startswith(glyph, i):
            total += value
            i += len(glyph)
    if i != len(s) or not 1 <= total <= 3999 or to_roman(total) != s:
        raise ValueError(s)
    return total
