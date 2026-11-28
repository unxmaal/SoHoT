# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [x * -2 for x in xs]
    xs = [x % 5 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[-2:]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [min(9, max(0, x)) for x in xs]
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = [x + -3 for x in xs]
    xs = [x * 2 for x in xs]
    xs = [abs(x) for x in xs]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x // 3 for x in xs]
    return sorted(xs)[:2]
