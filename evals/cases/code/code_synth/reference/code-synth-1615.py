# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 4 != 0]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    xs = [x for x in xs if x % 2 != 0]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x % 6 for x in xs]
    xs = xs[::-1]
    xs = [x * x for x in xs]
    xs = [x // 2 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [min(7, max(-1, x)) for x in xs]
    xs = xs[::-1]
    xs = [x * 5 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:4]
    return sum(xs)
