# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = xs[1:]
    xs = xs[::-1]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::3]
    xs = list(dict.fromkeys(xs))
    xs = [x + -5 for x in xs]
    xs = xs[-2:]
    xs = [x // 2 for x in xs]
    return xs.index(max(xs)) if xs else -1
