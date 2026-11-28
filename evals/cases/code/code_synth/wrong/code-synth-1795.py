# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [int(x / 2) for x in xs]
    xs = [min(-1, max(-4, x)) for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [x + -1 for x in xs]
    xs = [x * x for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::2]
    xs = [x for x in xs if x > -3]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-2:]
    xs = [min(7, max(-1, x)) for x in xs]
    xs = [int(x / 3) for x in xs]
    return max(xs) if xs else -1
