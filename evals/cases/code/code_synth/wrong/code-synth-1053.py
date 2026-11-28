# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [x // 2 for x in xs]
    xs = [x + 6 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * -1 for x in xs]
    xs = xs[-4:]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [min(9, max(1, x)) for x in xs]
    xs = [x for x in xs if x % 4 != 0]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x + -1 for x in xs]
    return xs
