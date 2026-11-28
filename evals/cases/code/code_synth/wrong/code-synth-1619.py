# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [x * 3 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x // 3 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [int(x / 2) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x // 2 for x in xs]
    xs = [x * x for x in xs]
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [x * -2 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = [x + 4 for x in xs]
    xs = sorted(xs)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [min(3, max(-4, x)) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    return len(set(xs))
