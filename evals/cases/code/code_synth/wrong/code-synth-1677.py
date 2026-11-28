# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = xs[-5:]
    xs = sorted(xs, reverse=True)
    xs = [x % 6 for x in xs]
    xs = [x * x for x in xs]
    xs = sorted(xs)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x // 4 for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x // 2 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    return xs
