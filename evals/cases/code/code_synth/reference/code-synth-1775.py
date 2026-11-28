# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [x + -3 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x // 2 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(6, max(-3, x)) for x in xs]
    xs = xs[::2]
    xs = [x + 9 for x in xs]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + 2 for x in xs]
    return sorted(xs)[:2]
