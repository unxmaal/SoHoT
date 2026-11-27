# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 2 != 0]
    xs = [x * 3 for x in xs]
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x >= 0]
    return xs.index(max(xs)) if xs else -1
