# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * x for x in xs]
    xs = xs[:6]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x + -1 for x in xs]
    xs = xs[::-1]
    xs = [x % 8 for x in xs]
    return len(set(xs))
