# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [abs(x) for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 5 != 0]
    xs = sorted(xs)
    xs = [x * x for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 2 for x in xs]
    xs = [x for x in xs if x > -3]
    xs = sorted(xs, key=abs)
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    return xs.index(max(xs)) if xs else -1
