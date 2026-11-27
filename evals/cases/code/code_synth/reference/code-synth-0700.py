# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = sorted(xs)
    xs = [int(x / 3) for x in xs]
    xs = [min(3, max(-4, x)) for x in xs]
    xs = [x + -1 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * 3 for x in xs]
    xs = [x * x for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs)
    xs = [x + 2 for x in xs]
    xs = [x * 3 for x in xs]
    return sum(xs)
