# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = sorted(xs, reverse=True)
    xs = [x * -2 for x in xs]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 3 != 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x >= 0]
    xs = [x + 9 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:6]
    xs = sorted(xs, key=abs)
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
