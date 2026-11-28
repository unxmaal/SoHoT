# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = xs[:6]
    xs = xs[-4:]
    xs = [min(2, max(-4, x)) for x in xs]
    xs = xs[:4]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, reverse=True)
    xs = xs[::-1]
    xs = [x + -9 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 8 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = xs[:2]
    xs = sorted(xs, key=abs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    return sum(xs)
