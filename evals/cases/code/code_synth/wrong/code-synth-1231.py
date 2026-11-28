# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [abs(x) for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [x * -1 for x in xs]
    xs = [int(x / 3) for x in xs]
    xs = xs[::3]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    return xs.index(max(xs)) if xs else -1
