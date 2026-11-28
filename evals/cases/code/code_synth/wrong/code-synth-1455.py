# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[-3:]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[-5:]
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = [min(4, max(0, x)) for x in xs]
    xs = xs[::3]
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 8 for x in xs]
    xs = xs[-4:]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    return xs
