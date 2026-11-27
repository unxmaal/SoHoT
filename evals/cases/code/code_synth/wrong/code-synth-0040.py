# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = xs[2:]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 7 != 0]
    xs = xs[2:]
    xs = sorted(xs)
    xs = [x % 7 for x in xs]
    xs = sorted(xs)
    xs = [x * -1 for x in xs]
    xs = xs[:5]
    return xs
