# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x * x for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = xs[::2]
    xs = [x * x for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x * -1 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x % 2 != 0]
    xs = [x % 4 for x in xs]
    xs = xs[::3]
    xs = xs[:5]
    xs = list(dict.fromkeys(xs))
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
