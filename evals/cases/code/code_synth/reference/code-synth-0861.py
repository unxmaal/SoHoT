# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [abs(x) for x in xs]
    xs = xs[:2]
    xs = xs[::2]
    xs = [x for x in xs if x > 0]
    xs = [x for x in xs if x % 2 == 0]
    xs = [int(x / 4) for x in xs]
    return sum(xs)
