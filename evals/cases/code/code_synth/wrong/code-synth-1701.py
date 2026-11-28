# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = xs[-3:]
    xs = [x // 2 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x // 2 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[1:]
    xs = [x % 9 for x in xs]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * -2 for x in xs]
    xs = sorted(xs)
    xs = [x + -3 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
