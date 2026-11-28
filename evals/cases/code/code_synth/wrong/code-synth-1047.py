# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [x // 3 for x in xs]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [x * 2 for x in xs]
    xs = xs[::-1]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x > 1]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = xs[::2]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    return sorted(xs)[:2]
