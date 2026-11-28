# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x + -5 for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [min(4, max(-1, x)) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[-3:]
    xs = sorted(xs, reverse=True)
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, reverse=True)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = [x % 6 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[::-1]
    xs = [int(x / 4) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    return sum(xs)
