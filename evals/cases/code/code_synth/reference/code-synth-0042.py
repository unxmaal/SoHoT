# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = sorted(xs)
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [min(9, max(1, x)) for x in xs]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [x for x in xs if x > -1]
    xs = [x * -1 for x in xs]
    xs = xs[:5]
    return sum(xs)
