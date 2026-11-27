# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[:3]
    xs = [abs(x) for x in xs]
    xs = [min(1, max(-4, x)) for x in xs]
    xs = [x % 7 for x in xs]
    xs = xs[:3]
    xs = sorted(xs)
    return xs.index(max(xs)) if xs else -1
