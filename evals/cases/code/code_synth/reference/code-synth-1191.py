# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [int(x / 3) for x in xs]
    xs = sorted(xs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::-1]
    xs = xs[::2]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x * x for x in xs]
    xs = xs[::-1]
    xs = [x + 4 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [int(x / 3) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs)
    xs = xs[::3]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = xs[-2:]
    xs = xs[:5]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    return xs
