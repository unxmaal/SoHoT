# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = xs[-4:]
    xs = [x % 5 for x in xs]
    xs = xs[1:]
    xs = [x % 4 for x in xs]
    xs = xs[:3]
    xs = [x + -9 for x in xs]
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = [x + -5 for x in xs]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [x % 9 for x in xs]
    xs = xs[:2]
    xs = [abs(x) for x in xs]
    return xs.index(max(xs)) if xs else -1
