# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * 5 for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [min(3, max(-2, x)) for x in xs]
    xs = [abs(x) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + 4 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x * 3 for x in xs]
    xs = xs[-3:]
    xs = [x for x in xs if x % 2 != 0]
    xs = sorted(xs, reverse=True)
    xs = [abs(x) for x in xs]
    return sorted(xs)[:2]
