# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [int(x / 2) for x in xs]
    xs = [x + -9 for x in xs]
    xs = xs[::-1]
    xs = [x for x in xs if x % 7 != 0]
    xs = sorted(xs, key=abs)
    xs = xs[:5]
    xs = sorted(xs, key=abs)
    xs = xs[1:]
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    return sorted(xs)[:2]
