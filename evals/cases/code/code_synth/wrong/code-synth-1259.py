# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [x + -1 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::-1]
    xs = sorted(xs)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs, reverse=True)
    xs = xs[:6]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x % 7 for x in xs]
    xs = xs[-3:]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::-1]
    xs = [x * x for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[:6]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
