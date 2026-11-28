# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [x for x in xs if x % 2 == 0]
    xs = [min(7, max(0, x)) for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = sorted(xs)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x * -1 for x in xs]
    xs = sorted(xs)
    xs = xs[::2]
    xs = [x % 9 for x in xs]
    return xs
