def match(pattern, s):
    tokens = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            tokens.append(("lit", pattern[i + 1]))
            i += 2
        elif c in "*?":
            tokens.append((c, None))
            i += 1
        else:
            tokens.append(("lit", c))
            i += 1
    prev = [True] + [False] * len(s)
    for kind, ch in tokens:
        cur = [False] * (len(s) + 1)
        if kind == "*":
            cur[0] = prev[0]
            for j in range(1, len(s) + 1):
                cur[j] = prev[j] or cur[j - 1]
        else:
            for j in range(1, len(s) + 1):
                cur[j] = prev[j - 1] and (kind == "?" or s[j - 1] == ch)
        prev = cur
    return prev[len(s)]
