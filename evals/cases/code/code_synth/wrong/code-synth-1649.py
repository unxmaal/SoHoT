# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [abs(x) for x in xs]
    xs = [x % 7 for x in xs]
    xs = [x // 3 for x in xs]
    xs = sorted(xs)
    xs = [x + -5 for x in xs]
    xs = [min(1, max(-5, x)) for x in xs]
    xs = xs[3:]
    xs = [x * x for x in xs]
    xs = xs[-5:]
    xs = sorted(xs, reverse=True)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x // 2 for x in xs]
    xs = xs[::-1]
    xs = xs[::2]
    xs = [x + -9 for x in xs]
    return sorted(xs)[:2]
