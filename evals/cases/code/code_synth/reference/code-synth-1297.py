# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x >= 0]
    xs = [x + 9 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    xs = [int(x / 4) for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > -2]
    xs = [x for x in xs if x % 2 != 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[:5]
    xs = [x for x in xs if x >= 0]
    xs = [min(6, max(1, x)) for x in xs]
    return len(set(xs))
