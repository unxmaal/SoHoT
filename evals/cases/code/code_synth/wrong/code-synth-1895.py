# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [x for x in xs if x % 4 != 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:6]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * x for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(xs))
    xs = [x % 7 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 2 for x in xs]
    xs = xs[-5:]
    return sorted(xs)[:2]
