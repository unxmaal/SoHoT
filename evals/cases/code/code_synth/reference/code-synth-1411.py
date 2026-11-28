# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x * x for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 4) for x in xs]
    xs = [x for x in xs if x > 5]
    xs = xs[:4]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [abs(x) for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    return xs
