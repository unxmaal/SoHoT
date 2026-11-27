# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [abs(x) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x for x in xs if x > 2]
    xs = sorted(xs, key=abs)
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    return sum(xs)
