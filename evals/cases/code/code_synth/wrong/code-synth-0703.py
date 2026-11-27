# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [abs(x) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x for x in xs if x > 2]
    xs = sorted(xs, key=abs)
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
