# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x % 2 != 0]
    xs = [x + -9 for x in xs]
    xs = sorted(xs, key=abs)
    return xs.index(max(xs)) if xs else -1
