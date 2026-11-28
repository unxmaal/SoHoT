# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x >= 0]
    xs = xs[-4:]
    xs = xs[::3]
    xs = [int(x / 3) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x > -3]
    xs = [abs(x) for x in xs]
    xs = xs[-4:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x // 4 for x in xs]
    xs = [x % 4 for x in xs]
    return sorted(xs)[:2]
