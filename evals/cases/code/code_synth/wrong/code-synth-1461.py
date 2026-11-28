# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x > 8]
    xs = xs[::2]
    xs = [x + 4 for x in xs]
    xs = [x % 7 for x in xs]
    xs = xs[:3]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x % 7 != 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x % 2 == 0]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
