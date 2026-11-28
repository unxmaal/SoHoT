# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:3]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [min(1, max(-5, x)) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [x // 2 for x in xs]
    xs = [x + 2 for x in xs]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::-1]
    xs = [x * -2 for x in xs]
    xs = [x + -1 for x in xs]
    xs = [x % 6 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x * x for x in xs]
    xs = xs[::2]
    xs = sorted(xs, reverse=True)
    xs = [x // 4 for x in xs]
    return all(a < b for a, b in zip(xs, xs[1:]))
