# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs)
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, reverse=True)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[-5:]
    xs = xs[::-1]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[:5]
    return sum(xs)
