# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[:5]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * 2 for x in xs]
    xs = xs[::-1]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x // 2 for x in xs]
    xs = xs[1:]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > 1]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [abs(x) for x in xs]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = xs[:5]
    return max(xs) if xs else -1
