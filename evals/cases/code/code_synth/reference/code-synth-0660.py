# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    xs = [x + -3 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[:6]
    xs = [x for x in xs if x > 3]
    xs = [int(x / 2) for x in xs]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    return sum(xs)
