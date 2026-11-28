# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [int(x / 4) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x % 5 for x in xs]
    xs = sorted(xs)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x % 2 == 0]
    xs = [abs(x) for x in xs]
    xs = xs[-3:]
    xs = [x + 6 for x in xs]
    return sorted(xs)[:2]
