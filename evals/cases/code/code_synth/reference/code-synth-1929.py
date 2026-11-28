# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = xs[-4:]
    xs = [x % 5 for x in xs]
    xs = xs[1:]
    xs = [x % 4 for x in xs]
    xs = xs[:3]
    xs = [x + -9 for x in xs]
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = [x + -5 for x in xs]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [x % 9 for x in xs]
    xs = xs[:2]
    xs = [abs(x) for x in xs]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
