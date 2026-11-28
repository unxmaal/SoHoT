# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x % 7 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x % 5 for x in xs]
    xs = xs[::-1]
    xs = [x * 2 for x in xs]
    xs = xs[:4]
    xs = [x + -9 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [int(x / 4) for x in xs]
    xs = [x + -1 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    return len(set(xs))
