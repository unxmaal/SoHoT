# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [x + 2 for x in xs]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[-3:]
    xs = [x * x for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [int(x / 4) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x // 2 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, reverse=True)
    xs = [x % 3 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * 3 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x * x for x in xs]
    xs = [x + 6 for x in xs]
    return len(set(xs))
