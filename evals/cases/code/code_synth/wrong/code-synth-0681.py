# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [x for x in xs if x > 1]
    xs = sorted(xs, key=abs)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x + 2 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = xs[::-1]
    xs = xs[::2]
    xs = [x * 3 for x in xs]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
