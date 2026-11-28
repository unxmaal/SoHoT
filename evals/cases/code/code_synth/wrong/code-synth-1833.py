# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = sorted(xs, reverse=True)
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x % 3 != 0]
    xs = [min(5, max(-4, x)) for x in xs]
    xs = [x % 3 for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x % 4 for x in xs]
    xs = xs[1:]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x + -1 for x in xs]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x % 6 for x in xs]
    xs = [abs(x) for x in xs]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
