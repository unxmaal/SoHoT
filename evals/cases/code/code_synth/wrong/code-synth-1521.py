# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = sorted(xs)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x % 4 != 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + 2 for x in xs]
    xs = [x * -2 for x in xs]
    xs = [min(-1, max(-5, x)) for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = [x + 2 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x % 2 != 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    return xs.index(max(xs)) if xs else -1
