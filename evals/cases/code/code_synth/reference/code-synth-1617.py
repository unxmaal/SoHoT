# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x // 3 for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[::-1]
    xs = sorted(xs)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [min(5, max(0, x)) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x % 7 for x in xs]
    xs = xs[:4]
    xs = xs[::-1]
    xs = xs[:6]
    xs = [x for x in xs if x % 7 != 0]
    xs = [x % 6 for x in xs]
    xs = [x * x for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    return xs.index(max(xs)) if xs else -1
