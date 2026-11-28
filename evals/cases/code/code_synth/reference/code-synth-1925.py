# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [x * -1 for x in xs]
    xs = [min(-1, max(-5, x)) for x in xs]
    xs = [x % 7 for x in xs]
    xs = sorted(xs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = xs[-4:]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs)
    xs = [x + 9 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x * x for x in xs]
    return xs
