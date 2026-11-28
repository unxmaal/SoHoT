# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [x % 6 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = [x * x for x in xs]
    xs = [x for x in xs if x > 6]
    xs = [x * -1 for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [int(x / 2) for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [x for x in xs if x % 3 != 0]
    xs = sorted(xs)
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[:6]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    return sorted(xs)[:2]
