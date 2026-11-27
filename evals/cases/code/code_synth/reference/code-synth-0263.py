# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = list(dict.fromkeys(xs))
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * -1 for x in xs]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return xs
