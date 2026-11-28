# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x > 7]
    xs = [abs(x) for x in xs]
    xs = [x * -1 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x * x for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [min(2, max(-1, x)) for x in xs]
    xs = [x % 5 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    return max(xs) if xs else -1
