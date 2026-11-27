# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x for x in xs if x % 2 == 0]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * 3 for x in xs]
    xs = [x for x in xs if x % 5 != 0]
    xs = [x for x in xs if x >= 0]
    return xs
