# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = sorted(xs, reverse=True)
    xs = sorted(xs)
    xs = sorted(xs, reverse=True)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [x for x in xs if x > 8]
    xs = xs[:5]
    xs = [x // 4 for x in xs]
    xs = [x * x for x in xs]
    xs = xs[:6]
    xs = [int(x / 3) for x in xs]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = sorted(xs)
    xs = [x // 2 for x in xs]
    xs = xs[1:]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
