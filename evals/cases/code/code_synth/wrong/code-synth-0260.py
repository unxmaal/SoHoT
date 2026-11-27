# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [x for x in xs if x % 7 != 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 9 for x in xs]
    xs = [x * 5 for x in xs]
    xs = [x * x for x in xs]
    xs = [x % 6 for x in xs]
    xs = sorted(xs)
    xs = xs[::3]
    return max(xs) if xs else -1
