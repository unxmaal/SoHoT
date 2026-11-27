# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = sorted(xs, reverse=True)
    xs = xs[:5]
    xs = [x for x in xs if x > -2]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    return len(set(xs))
