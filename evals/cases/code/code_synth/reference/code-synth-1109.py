# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x > 4]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = xs[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:5]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs)
    xs = list(dict.fromkeys(xs))
    xs = [x * 2 for x in xs]
    xs = [x + -5 for x in xs]
    return len(set(xs))
