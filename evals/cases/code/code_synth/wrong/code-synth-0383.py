# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, key=abs)
    xs = sorted(xs)
    xs = xs[2:]
    xs = [x * x for x in xs]
    xs = sorted(xs)
    xs = sorted(xs, key=abs)
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    return max(xs) if xs else -1
