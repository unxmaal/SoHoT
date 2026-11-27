# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x for x in xs if x > 1]
    xs = sorted(xs, key=abs)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x + 2 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = xs[::-1]
    xs = xs[::2]
    xs = [x * 3 for x in xs]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
