# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = xs[::-1]
    xs = [x for x in xs if x >= 0]
    xs = xs[::3]
    xs = sorted(xs, key=abs)
    xs = [x * 5 for x in xs]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    return xs
