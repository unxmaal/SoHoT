# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = xs[::3]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x > 2]
    xs = [x for x in xs if x >= 0]
    xs = [min(9, max(0, x)) for x in xs]
    xs = sorted(xs)
    return max(xs) if xs else -1
