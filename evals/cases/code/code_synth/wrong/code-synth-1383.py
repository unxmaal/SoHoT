# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [int(x / 2) for x in xs]
    xs = xs[::2]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, key=abs)
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x % 7 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [abs(x) for x in xs]
    xs = [x + 9 for x in xs]
    xs = [x * -2 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[:6]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
