# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = sorted(xs, key=abs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [int(x / 2) for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x * 3 for x in xs]
    xs = sorted(xs, key=abs)
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [min(9, max(0, x)) for x in xs]
    xs = sorted(xs, reverse=True)
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    return sorted(xs)[:2]
