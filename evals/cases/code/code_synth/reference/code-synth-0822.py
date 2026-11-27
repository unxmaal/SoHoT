# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = list(dict.fromkeys(xs))
    xs = [abs(x) for x in xs]
    xs = xs[:6]
    xs = sorted(xs, key=abs)
    xs = [x // 3 for x in xs]
    xs = [int(x / 3) for x in xs]
    xs = [min(4, max(-4, x)) for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
