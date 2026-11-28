# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x % 2 != 0]
    xs = xs[:3]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(xs))
    xs = xs[-5:]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [x % 9 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [int(x / 4) for x in xs]
    xs = list(dict.fromkeys(xs))
    return sum(xs)
