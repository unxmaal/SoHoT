# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [x for x in xs if x % 5 != 0]
    xs = sorted(xs)
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x % 9 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    xs = xs[:3]
    return xs.index(max(xs)) if xs else -1
