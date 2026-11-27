# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x for x in xs if x % 5 != 0]
    xs = sorted(xs)
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x % 9 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    xs = xs[:3]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
