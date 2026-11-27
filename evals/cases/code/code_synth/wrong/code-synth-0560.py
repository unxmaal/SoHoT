# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x + -9 for x in xs]
    xs = [x * 5 for x in xs]
    xs = xs[:6]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x % 2 == 0]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
