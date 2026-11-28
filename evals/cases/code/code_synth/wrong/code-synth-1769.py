# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [x * x for x in xs]
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = sorted(xs)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(xs))
    xs = xs[2:]
    xs = xs[-3:]
    return max(xs) if xs else -1
