# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs)
    xs = [x + 9 for x in xs]
    xs = [x for x in xs if x > -2]
    xs = [min(6, max(-3, x)) for x in xs]
    xs = [x % 7 for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = xs[-4:]
    xs = xs[::-1]
    xs = [x + 4 for x in xs]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [abs(x) for x in xs]
    return len(set(xs))
