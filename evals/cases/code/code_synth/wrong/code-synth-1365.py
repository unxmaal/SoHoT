# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[::2]
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x + 9 for x in xs]
    xs = [x * x for x in xs]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::-1]
    xs = xs[:6]
    xs = [x * x for x in xs]
    return xs.index(max(xs)) if xs else -1
