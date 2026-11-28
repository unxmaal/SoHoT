# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x % 2 == 0]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x * 5 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + 6 for x in xs]
    xs = [x % 7 for x in xs]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * x for x in xs]
    xs = [x // 4 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
