# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x + -9 for x in xs]
    xs = [x * 5 for x in xs]
    xs = xs[:6]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x % 2 == 0]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
