# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = xs[1:]
    xs = [x // 4 for x in xs]
    xs = [x for x in xs if x % 3 != 0]
    xs = xs[::2]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[1:]
    xs = [min(3, max(-4, x)) for x in xs]
    xs = [x for x in xs if x > 1]
    xs = sorted(xs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = xs[-3:]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    return sum(xs)
