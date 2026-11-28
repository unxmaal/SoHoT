# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = xs[2:]
    xs = [x * 2 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x + 2 for x in xs]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * -1 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * x for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:5]
    xs = [x for x in xs if x >= 0]
    xs = xs[:4]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::2]
    return sorted(xs)[:2]
