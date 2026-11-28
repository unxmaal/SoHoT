# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * x for x in xs]
    xs = [min(3, max(-3, x)) for x in xs]
    xs = xs[2:]
    xs = xs[-4:]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x // 3 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
