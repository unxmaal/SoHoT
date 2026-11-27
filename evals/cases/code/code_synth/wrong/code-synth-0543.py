# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [int(x / 2) for x in xs]
    xs = [x * -1 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x // 4 for x in xs]
    xs = xs[:4]
    return sum(xs)
