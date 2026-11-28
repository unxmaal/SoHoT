# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x > -3]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > 4]
    xs = [int(x / 2) for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = xs[:4]
    xs = xs[-5:]
    xs = xs[::3]
    xs = xs[:4]
    xs = xs[::-1]
    xs = [x % 3 for x in xs]
    xs = xs[:5]
    xs = [int(x / 3) for x in xs]
    return xs
