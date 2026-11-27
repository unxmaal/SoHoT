# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 4 != 0]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-5:]
    xs = [abs(x) for x in xs]
    xs = xs[:5]
    xs = [x for x in xs if x > 3]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 5 for x in xs]
    return sorted(xs)[:2]
