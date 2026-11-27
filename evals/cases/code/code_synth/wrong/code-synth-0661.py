# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs)
    xs = [x for x in xs if x >= 0]
    xs = [int(x / 4) for x in xs]
    xs = xs[:4]
    xs = [x * x for x in xs]
    return max(xs) if xs else -1
