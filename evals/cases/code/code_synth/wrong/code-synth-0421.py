# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x > 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x > 2]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
