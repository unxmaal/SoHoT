# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x > 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x > 2]
    return xs.index(max(xs)) if xs else -1
