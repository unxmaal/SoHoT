# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [x * -2 for x in xs]
    xs = [x * x for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = [min(5, max(-2, x)) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 4 != 0]
    return sum(xs)
