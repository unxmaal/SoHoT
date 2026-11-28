# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [abs(x) for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::-1]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs, reverse=True)
    xs = [x * 5 for x in xs]
    xs = sorted(xs)
    xs = sorted(xs, reverse=True)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 8 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [int(x / 2) for x in xs]
    return max(xs) if xs else -1
