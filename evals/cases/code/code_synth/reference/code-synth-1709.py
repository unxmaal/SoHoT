# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::-1]
    xs = [x * -2 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs, reverse=True)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = list(dict.fromkeys(xs))
    xs = [min(3, max(-4, x)) for x in xs]
    xs = xs[::-1]
    xs = [x * -2 for x in xs]
    xs = xs[::-1]
    xs = [x for x in xs if x > -3]
    xs = [x for x in xs if x % 2 == 0]
    return xs
