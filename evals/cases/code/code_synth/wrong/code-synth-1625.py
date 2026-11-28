# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = xs[:6]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * x for x in xs]
    xs = [x * 3 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [abs(x) for x in xs]
    xs = [x // 3 for x in xs]
    xs = [x for x in xs if x > -1]
    xs = xs[::3]
    return all(a < b for a, b in zip(xs, xs[1:]))
