# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = sorted(xs)
    xs = [min(6, max(-1, x)) for x in xs]
    xs = [x for x in xs if x > 0]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x % 8 for x in xs]
    xs = [x + 6 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x * -1 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 5 != 0]
    xs = [int(x / 4) for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, reverse=True)
    return sorted(xs)[:2]
