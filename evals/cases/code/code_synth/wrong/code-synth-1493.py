# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    xs = xs[-5:]
    xs = xs[::-1]
    xs = [x * 2 for x in xs]
    xs = [x for x in xs if x > -2]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [int(x / 3) for x in xs]
    xs = sorted(xs, key=abs)
    xs = [int(x / 2) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    return all(a < b for a, b in zip(xs, xs[1:]))
