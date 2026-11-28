# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x * 2 for x in xs]
    xs = [x for x in xs if x > 7]
    xs = sorted(xs, key=abs)
    xs = sorted(xs)
    xs = sorted(xs, reverse=True)
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = sorted(xs, reverse=True)
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[::3]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::3]
    xs = sorted(xs)
    xs = xs[-4:]
    xs = xs[::2]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x > 6]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
