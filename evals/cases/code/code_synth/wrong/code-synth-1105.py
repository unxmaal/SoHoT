# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [min(2, max(-3, x)) for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x * -2 for x in xs]
    xs = [min(9, max(1, x)) for x in xs]
    xs = xs[:2]
    xs = xs[-3:]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::2]
    xs = [x for x in xs if x % 2 == 0]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, key=abs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x % 5 for x in xs]
    return max(xs) if xs else -1
