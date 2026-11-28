# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x + 6 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[-2:]
    xs = sorted(xs, key=abs)
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:4]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = xs[:6]
    xs = [x * x for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:5]
    xs = sorted(xs)
    xs = [x * 3 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[-4:]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    return max(xs) if xs else -1
