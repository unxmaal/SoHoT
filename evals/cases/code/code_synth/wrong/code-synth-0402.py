# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x > 6]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [x * 2 for x in xs]
    xs = [x * 2 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = [x * x for x in xs]
    return xs
