# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(8, max(0, x)) for x in xs]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [min(5, max(1, x)) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * -2 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x * 3 for x in xs]
    xs = sorted(xs)
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[::2]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [int(x / 3) for x in xs]
    xs = xs[-4:]
    xs = [x // 2 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    return xs.index(max(xs)) if xs else -1
