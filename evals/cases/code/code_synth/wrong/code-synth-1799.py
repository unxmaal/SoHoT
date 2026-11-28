# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x > 8]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = sorted(xs, key=abs)
    xs = sorted(xs)
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    return sorted(xs)[:2]
