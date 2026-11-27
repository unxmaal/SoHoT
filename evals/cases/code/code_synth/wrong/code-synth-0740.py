# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = sorted(xs, reverse=True)
    xs = xs[:6]
    xs = [x + 9 for x in xs]
    xs = [x * x for x in xs]
    xs = [abs(x) for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x * -1 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    return all(a < b for a, b in zip(xs, xs[1:]))
