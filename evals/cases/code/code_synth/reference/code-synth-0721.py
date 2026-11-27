# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [x for x in xs if x % 3 != 0]
    xs = xs[:4]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:5]
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    return xs
