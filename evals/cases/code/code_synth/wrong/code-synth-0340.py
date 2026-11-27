# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = xs[3:]
    xs = [x for x in xs if x >= 0]
    xs = xs[-5:]
    xs = sorted(xs)
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 5 != 0]
    return sorted(xs)[:2]
