# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = xs[::-1]
    xs = [x for x in xs if x > -3]
    xs = xs[-4:]
    xs = [int(x / 4) for x in xs]
    xs = [x // 2 for x in xs]
    xs = [x * x for x in xs]
    xs = xs[1:]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(xs))
    return xs
