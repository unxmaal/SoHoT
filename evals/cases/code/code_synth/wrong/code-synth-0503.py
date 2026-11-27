# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = xs[::3]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x > 2]
    xs = [x for x in xs if x >= 0]
    xs = [min(9, max(0, x)) for x in xs]
    xs = sorted(xs)
    return max(xs) if xs else -1
