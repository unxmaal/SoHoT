# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [x * x for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x + -9 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = [x * x for x in xs]
    xs = [x * 2 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    return xs
