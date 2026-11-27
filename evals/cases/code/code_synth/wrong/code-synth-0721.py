# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [x for x in xs if x % 3 != 0]
    xs = xs[:4]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:5]
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
