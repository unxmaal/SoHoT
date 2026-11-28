# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x + 9 for x in xs]
    xs = sorted(xs)
    xs = [x % 5 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x * -2 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [int(x / 4) for x in xs]
    xs = [x // 3 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [min(1, max(-4, x)) for x in xs]
    xs = [x + -9 for x in xs]
    xs = [min(2, max(-5, x)) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 2 != 0]
    return xs
