# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [x * -1 for x in xs]
    xs = [x for x in xs if x % 4 != 0]
    xs = [int(x / 3) for x in xs]
    xs = [x % 6 for x in xs]
    xs = [x for x in xs if x > 1]
    xs = [x // 3 for x in xs]
    return xs.index(max(xs)) if xs else -1
