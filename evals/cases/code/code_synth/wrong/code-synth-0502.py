# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [int(x / 4) for x in xs]
    xs = [x for x in xs if x % 3 != 0]
    xs = sorted(xs)
    xs = xs[-2:]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 2) for x in xs]
    return all(a < b for a, b in zip(xs, xs[1:]))
