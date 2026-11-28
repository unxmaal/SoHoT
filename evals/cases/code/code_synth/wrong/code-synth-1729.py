# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs)
    xs = sorted(xs, key=abs)
    xs = [x % 6 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [min(4, max(1, x)) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[-4:]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    return xs
