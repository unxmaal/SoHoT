# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = sorted(xs, reverse=True)
    xs = xs[:5]
    xs = [x for x in xs if x > -2]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    return all(a < b for a, b in zip(xs, xs[1:]))
