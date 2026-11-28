# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[1:]
    xs = sorted(xs, reverse=True)
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + 9 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = [x * x for x in xs]
    xs = [x + -9 for x in xs]
    xs = [x // 2 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x // 3 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [int(x / 4) for x in xs]
    return max(xs) if xs else -1
