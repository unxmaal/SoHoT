# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 4 != 0]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-5:]
    xs = [abs(x) for x in xs]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:5]
    xs = [x for x in xs if x > 3]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 5 for x in xs]
    return sorted(xs)[:2]
