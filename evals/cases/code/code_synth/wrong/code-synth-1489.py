# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [x for x in xs if x > 2]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x + -5 for x in xs]
    xs = xs[::-1]
    xs = [x * 5 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = sorted(xs, reverse=True)
    xs = [min(5, max(-1, x)) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    xs = [x * 2 for x in xs]
    xs = xs[-4:]
    xs = [x % 3 for x in xs]
    return xs
