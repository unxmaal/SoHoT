# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[::3]
    xs = [min(1, max(-4, x)) for x in xs]
    xs = xs[-3:]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::-1]
    return sum(xs)
