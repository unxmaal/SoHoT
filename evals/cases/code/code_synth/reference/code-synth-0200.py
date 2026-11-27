# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [x + 9 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x > 8]
    xs = [x % 9 for x in xs]
    xs = [int(x / 3) for x in xs]
    xs = [x * 5 for x in xs]
    xs = sorted(xs)
    xs = [int(x / 4) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x + 4 for x in xs]
    return sorted(xs)[:2]
