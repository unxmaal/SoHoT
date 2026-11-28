# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [x for x in xs if x > 5]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [min(1, max(-3, x)) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = sorted(xs, key=abs)
    xs = xs[-3:]
    xs = [int(x / 3) for x in xs]
    xs = [x % 6 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x >= 0]
    xs = xs[::2]
    xs = [x * 2 for x in xs]
    xs = [x + 2 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x > 2]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    return max(xs) if xs else -1
