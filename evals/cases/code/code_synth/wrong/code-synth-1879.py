# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = xs[::2]
    xs = xs[-3:]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(8, max(-1, x)) for x in xs]
    xs = [x * -1 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = list(dict.fromkeys(xs))
    xs = xs[:4]
    xs = xs[-3:]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs, key=abs)
    xs = sorted(xs)
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    return len(set(xs))
