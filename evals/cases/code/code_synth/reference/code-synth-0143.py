# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[:3]
    xs = [abs(x) for x in xs]
    xs = [min(1, max(-4, x)) for x in xs]
    xs = [x % 7 for x in xs]
    xs = xs[:3]
    xs = sorted(xs)
    return xs.index(max(xs)) if xs else -1
