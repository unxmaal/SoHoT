# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 3 for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = xs[::3]
    xs = xs[1:]
    xs = [x for x in xs if x > 6]
    xs = xs[::-1]
    xs = [x + 6 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 3 for x in xs]
    xs = xs[::-1]
    return max(xs) if xs else -1
