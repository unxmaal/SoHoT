# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 6 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x // 2 for x in xs]
    xs = [x + -5 for x in xs]
    xs = xs[:5]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 5 for x in xs]
    return xs
