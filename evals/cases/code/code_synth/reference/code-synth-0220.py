# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = xs[::2]
    xs = [abs(x) for x in xs]
    xs = xs[3:]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x > 3]
    xs = [x + -1 for x in xs]
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::-1]
    xs = [x for x in xs if x > -2]
    xs = sorted(xs, reverse=True)
    return sorted(xs)[:2]
