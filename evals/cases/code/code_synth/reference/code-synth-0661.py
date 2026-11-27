# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs)
    xs = [x for x in xs if x >= 0]
    xs = [int(x / 4) for x in xs]
    xs = xs[:4]
    xs = [x * x for x in xs]
    return xs.index(max(xs)) if xs else -1
