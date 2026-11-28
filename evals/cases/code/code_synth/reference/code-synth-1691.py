# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x // 3 for x in xs]
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[-3:]
    xs = xs[:2]
    xs = sorted(xs)
    xs = [x // 4 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    return xs
