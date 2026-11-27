# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = xs[-3:]
    xs = sorted(xs)
    xs = sorted(xs, key=abs)
    xs = [x * 5 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x // 2 for x in xs]
    xs = xs[::2]
    return sorted(xs)[:2]
