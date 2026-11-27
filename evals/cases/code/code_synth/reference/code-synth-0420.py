# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [x % 8 for x in xs]
    xs = [int(x / 3) for x in xs]
    xs = xs[2:]
    xs = sorted(xs, key=abs)
    xs = xs[-5:]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(2, max(-4, x)) for x in xs]
    xs = sorted(xs, reverse=True)
    return len(set(xs))
