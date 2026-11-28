# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 2 == 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs)
    xs = [abs(x) for x in xs]
    xs = [x + 2 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 4) for x in xs]
    xs = [min(5, max(1, x)) for x in xs]
    xs = [int(x / 3) for x in xs]
    xs = [x * x for x in xs]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    return len(set(xs))
