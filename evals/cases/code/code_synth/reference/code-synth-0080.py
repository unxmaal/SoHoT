# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x * 3 for x in xs]
    xs = sorted(xs, key=abs)
    xs = sorted(xs, reverse=True)
    xs = xs[::2]
    xs = [int(x / 2) for x in xs]
    return sorted(xs)[:2]
