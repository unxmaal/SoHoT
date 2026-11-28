# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[::2]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [x * x for x in xs]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = [x % 7 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [min(7, max(-2, x)) for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x // 3 for x in xs]
    xs = [x % 9 for x in xs]
    xs = [x for x in xs if x >= 0]
    return sorted(xs)[:2]
