# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[1:]
    xs = [min(4, max(1, x)) for x in xs]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = xs[::2]
    xs = [x for x in xs if x >= 0]
    return xs.index(max(xs)) if xs else -1
