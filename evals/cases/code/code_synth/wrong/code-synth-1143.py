# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [x for x in xs if x % 2 == 0]
    xs = sorted(xs)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = [x // 4 for x in xs]
    xs = [x * -2 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-3:]
    xs = [x for x in xs if x % 7 != 0]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
