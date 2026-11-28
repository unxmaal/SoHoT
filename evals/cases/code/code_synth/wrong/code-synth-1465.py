# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs)
    xs = [abs(x) for x in xs]
    xs = xs[::2]
    xs = sorted(xs, reverse=True)
    xs = [int(x / 3) for x in xs]
    xs = sorted(xs, key=abs)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs)
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = [x + -3 for x in xs]
    xs = sorted(xs, reverse=True)
    return xs.index(max(xs)) if xs else -1
