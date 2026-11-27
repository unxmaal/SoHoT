# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [int(x / 4) for x in xs]
    xs = xs[::-1]
    xs = [x % 5 for x in xs]
    xs = sorted(xs)
    xs = [x % 6 for x in xs]
    xs = sorted(xs, key=abs)
    xs = xs[-5:]
    return sorted(xs)[:2]
