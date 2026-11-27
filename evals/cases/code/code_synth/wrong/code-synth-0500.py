# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = xs[::2]
    xs = [x * 5 for x in xs]
    xs = xs[::2]
    xs = [x * -2 for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::2]
    return xs
