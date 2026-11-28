# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [int(x / 4) for x in xs]
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = xs[2:]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > -1]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x + 9 for x in xs]
    xs = xs[::2]
    xs = [int(x / 2) for x in xs]
    xs = [x % 9 for x in xs]
    return sum(xs)
