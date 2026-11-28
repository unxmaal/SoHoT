# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[2:]
    xs = [int(x / 4) for x in xs]
    xs = xs[-5:]
    xs = [min(6, max(1, x)) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x + 6 for x in xs]
    xs = xs[:4]
    xs = [x // 3 for x in xs]
    xs = [x * -2 for x in xs]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = xs[::-1]
    xs = [x for x in xs if x >= 0]
    return all(a < b for a, b in zip(xs, xs[1:]))
