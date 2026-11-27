# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = sorted(xs)
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [min(9, max(1, x)) for x in xs]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [x for x in xs if x > -1]
    xs = [x * -1 for x in xs]
    xs = xs[:5]
    return all(a < b for a, b in zip(xs, xs[1:]))
