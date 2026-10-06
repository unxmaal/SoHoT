def evaluate(s):
    tokens = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
        elif c.isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            tokens.append(int(s[i:j]))
            i = j
        elif c in "+-*/()":
            tokens.append(c)
            i += 1
        else:
            raise ValueError(f"bad character {c!r}")
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take():
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("unexpected end")
        pos += 1
        return tokens[pos - 1]

    def expr():
        value = term()
        while peek() in ("+", "-"):
            value = value + term() if take() == "+" else value - term()
        return value

    def term():
        value = factor()
        while peek() in ("*", "/"):
            if take() == "*":
                value *= factor()
            else:
                value /= factor()
        return value

    def factor():
        t = take()
        if t == "-":
            return -factor()
        if t == "(":
            value = expr()
            if take() != ")":
                raise ValueError("unbalanced")
            return value
        if isinstance(t, int):
            return float(t)
        raise ValueError(f"unexpected {t!r}")

    result = expr()
    if pos != len(tokens):
        raise ValueError("trailing input")
    return float(result)
