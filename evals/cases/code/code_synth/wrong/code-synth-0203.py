# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [int(x / 4) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = xs[::-1]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [int(x / 3) for x in xs]
    xs = [x % 4 for x in xs]
    return xs.index(max(xs)) if xs else -1
