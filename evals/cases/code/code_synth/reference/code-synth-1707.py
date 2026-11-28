# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(xs))
    xs = [x + 6 for x in xs]
    xs = xs[::2]
    xs = sorted(xs, reverse=True)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = [x for x in xs if x % 2 == 0]
    xs = [int(x / 4) for x in xs]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * x for x in xs]
    return sorted(xs)[:2]
