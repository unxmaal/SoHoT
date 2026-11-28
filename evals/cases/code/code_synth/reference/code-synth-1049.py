# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 2 for x in xs]
    xs = [x * x for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::-1]
    xs = [x % 5 for x in xs]
    xs = sorted(xs)
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[-2:]
    xs = sorted(xs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 4 != 0]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = [x * -2 for x in xs]
    return sum(xs)
