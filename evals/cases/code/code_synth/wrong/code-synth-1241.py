# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [int(x / 3) for x in xs]
    xs = [x * 5 for x in xs]
    xs = [min(4, max(-2, x)) for x in xs]
    xs = sorted(xs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 5 for x in xs]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = [int(x / 3) for x in xs]
    return sorted(xs)[:2]
