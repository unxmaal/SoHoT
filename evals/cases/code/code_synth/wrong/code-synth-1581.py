# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x for x in xs if x >= 0]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x + -3 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[-4:]
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 4 for x in xs]
    xs = [x * x for x in xs]
    xs = [x + 2 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x % 2 == 0]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, reverse=True)
    return xs
