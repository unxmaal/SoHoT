# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [int(x / 3) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[:4]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x // 2 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[:2]
    xs = sorted(xs)
    xs = [x + 2 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    xs = [min(4, max(-1, x)) for x in xs]
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = xs[::2]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x + -3 for x in xs]
    return max(xs) if xs else -1
