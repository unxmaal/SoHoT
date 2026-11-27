# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [x * -1 for x in xs]
    xs = [x for x in xs if x % 4 != 0]
    xs = [int(x / 3) for x in xs]
    xs = [x % 6 for x in xs]
    xs = [x for x in xs if x > 1]
    xs = [x // 3 for x in xs]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
