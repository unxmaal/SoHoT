# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [x for x in xs if x % 2 == 0]
    xs = [min(5, max(0, x)) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[::3]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [min(4, max(-1, x)) for x in xs]
    return xs
