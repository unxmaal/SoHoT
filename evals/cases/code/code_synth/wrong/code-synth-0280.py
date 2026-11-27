# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [x for x in xs if x % 2 == 0]
    xs = [min(5, max(0, x)) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [min(4, max(-1, x)) for x in xs]
    return xs
