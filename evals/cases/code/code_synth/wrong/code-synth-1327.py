# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[:6]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * -2 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x % 9 for x in xs]
    xs = sorted(xs, key=abs)
    xs = sorted(xs, reverse=True)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = xs[::-1]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
