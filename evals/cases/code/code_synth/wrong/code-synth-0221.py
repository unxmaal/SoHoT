# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = xs[:3]
    xs = [x for x in xs if x > 7]
    return all(a < b for a, b in zip(xs, xs[1:]))
