# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(4, max(0, x)) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * x for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [int(x / 3) for x in xs]
    xs = [x * x for x in xs]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x > 1]
    xs = xs[:6]
    xs = xs[::2]
    xs = xs[::-1]
    xs = [x // 2 for x in xs]
    return sum(xs)
