# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = xs[:6]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * x for x in xs]
    xs = [x * 3 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [abs(x) for x in xs]
    xs = [x // 3 for x in xs]
    xs = [x for x in xs if x > -1]
    xs = xs[::3]
    return sum(xs)
