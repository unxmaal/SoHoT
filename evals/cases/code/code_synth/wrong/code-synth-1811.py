# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x for x in xs if x % 2 == 0]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [int(x / 4) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs, reverse=True)
    xs = [x + 6 for x in xs]
    xs = [x * x for x in xs]
    return max(xs) if xs else -1
