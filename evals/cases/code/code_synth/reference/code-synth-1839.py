# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = xs[::-1]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [x * x for x in xs]
    xs = xs[1:]
    xs = [x * x for x in xs]
    xs = [x + 4 for x in xs]
    xs = [x * 2 for x in xs]
    xs = [x % 9 for x in xs]
    xs = [x * x for x in xs]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [int(x / 2) for x in xs]
    xs = [x % 6 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    return xs
