# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = sorted(xs, key=abs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(4, max(1, x)) for x in xs]
    xs = [x * 2 for x in xs]
    xs = [min(7, max(-1, x)) for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x + -3 for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = [int(x / 4) for x in xs]
    xs = [min(8, max(-1, x)) for x in xs]
    xs = [x * x for x in xs]
    return xs
