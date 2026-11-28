# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x // 2 for x in xs]
    xs = [min(6, max(-2, x)) for x in xs]
    xs = sorted(xs, key=abs)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [int(x / 4) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::2]
    xs = sorted(xs, key=abs)
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * 2 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs)
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    return max(xs) if xs else -1
