# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x % 4 != 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    xs = xs[-2:]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for x in xs if x % 2 == 0]
    xs = [abs(x) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 5 for x in xs]
    xs = [int(x / 3) for x in xs]
    xs = xs[::3]
    xs = [int(x / 3) for x in xs]
    xs = [min(5, max(-4, x)) for x in xs]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [abs(x) for x in xs]
    xs = [x * 3 for x in xs]
    xs = xs[-5:]
    return sorted(xs)[:2]
