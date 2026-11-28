# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = xs[3:]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, key=abs)
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, reverse=True)
    xs = xs[-3:]
    xs = sorted(xs)
    xs = [x + -1 for x in xs]
    xs = xs[:4]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    return sorted(xs)[:2]
