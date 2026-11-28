# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [x * x for x in xs]
    xs = sorted(xs)
    xs = sorted(xs, key=abs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(5, max(-3, x)) for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * 2 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    return sorted(xs)[:2]
