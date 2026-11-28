# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[::-1]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x % 5 for x in xs]
    xs = xs[::2]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = xs[:2]
    xs = [min(5, max(0, x)) for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 4 != 0]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
