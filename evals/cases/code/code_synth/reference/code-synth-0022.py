# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = xs[::3]
    xs = xs[:2]
    xs = [min(5, max(-1, x)) for x in xs]
    xs = sorted(xs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(8, max(1, x)) for x in xs]
    xs = xs[:4]
    return max(xs) if xs else -1
