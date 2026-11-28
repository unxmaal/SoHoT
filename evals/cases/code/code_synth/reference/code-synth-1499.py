# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [x + -5 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, reverse=True)
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x > 1]
    xs = [x // 2 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    xs = sorted(xs)
    xs = [x + -1 for x in xs]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x % 2 == 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = xs[::3]
    return sorted(xs)[:2]
