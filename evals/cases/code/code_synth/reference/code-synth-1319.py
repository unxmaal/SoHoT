# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > 7]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x * 5 for x in xs]
    xs = [min(1, max(-5, x)) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[:5]
    xs = xs[::-1]
    xs = sorted(xs)
    return xs
