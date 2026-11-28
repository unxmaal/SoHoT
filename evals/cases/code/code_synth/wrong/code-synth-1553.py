# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [x * -1 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * -2 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-4:]
    xs = sorted(xs)
    xs = sorted(xs, key=abs)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::-1]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = sorted(xs)
    xs = [x for x in xs if x >= 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x + -1 for x in xs]
    xs = [x * x for x in xs]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
