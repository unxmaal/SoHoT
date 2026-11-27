# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [int(x / 2) for x in xs]
    xs = [x + -9 for x in xs]
    xs = xs[::-1]
    xs = [x for x in xs if x % 7 != 0]
    xs = sorted(xs, key=abs)
    xs = xs[:5]
    xs = sorted(xs, key=abs)
    xs = xs[1:]
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
