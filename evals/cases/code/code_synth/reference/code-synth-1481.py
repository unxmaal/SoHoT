# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x + -9 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [min(8, max(0, x)) for x in xs]
    xs = sorted(xs, key=abs)
    xs = [int(x / 2) for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x + 4 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x // 2 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = xs[:5]
    return xs
