# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = xs[::3]
    xs = xs[2:]
    xs = [int(x / 4) for x in xs]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x + 2 for x in xs]
    xs = [x for x in xs if x % 5 != 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[:3]
    xs = sorted(xs)
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    xs = xs[::2]
    xs = xs[:3]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:2]
    xs = sorted(xs)
    xs = [abs(x) for x in xs]
    return sorted(xs)[:2]
