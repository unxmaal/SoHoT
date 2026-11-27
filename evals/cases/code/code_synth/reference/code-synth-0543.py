# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [int(x / 2) for x in xs]
    xs = [x * -1 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x // 4 for x in xs]
    xs = xs[:4]
    xs = [x * x for x in xs]
    return sum(xs)
