# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = list(dict.fromkeys(xs))
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [abs(x) for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x * -2 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x >= 0]
    xs = xs[::-1]
    xs = xs[:2]
    xs = [x for x in xs if x % 5 != 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [int(x / 3) for x in xs]
    xs = xs[:3]
    return sorted(xs)[:2]
