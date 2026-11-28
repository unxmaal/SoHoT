# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [int(x / 4) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x * x for x in xs]
    xs = xs[::2]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(xs))
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + -3 for x in xs]
    xs = [x * -1 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x % 2 == 0]
    xs = [int(x / 3) for x in xs]
    xs = [x % 7 for x in xs]
    return len(set(xs))
