# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [x % 5 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs, key=abs)
    xs = sorted(xs, reverse=True)
    xs = [min(4, max(0, x)) for x in xs]
    xs = xs[:5]
    xs = xs[-2:]
    xs = [x for x in xs if x % 2 == 0]
    return len(set(xs))
