# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::-1]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, reverse=True)
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::-1]
    xs = [x // 2 for x in xs]
    xs = [x * -1 for x in xs]
    xs = [abs(x) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x * x for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x // 3 for x in xs]
    xs = [min(4, max(-4, x)) for x in xs]
    xs = [x % 6 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x * -1 for x in xs]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
