# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[:6]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(xs))
    xs = xs[::3]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [min(2, max(-3, x)) for x in xs]
    xs = [x * 5 for x in xs]
    xs = [x for x in xs if x > -2]
    xs = sorted(xs, key=abs)
    xs = [x % 3 for x in xs]
    return xs
